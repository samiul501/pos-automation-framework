# ============================================================
# BUSINESS ACTIONS - login, transaction, hold/recall, exchange,
# return, payment. Add new flows/features here.
# ============================================================

import time
import allure
from pywinauto.keyboard import send_keys

import config
import pos_helpers as h


def do_login():
    with allure.step("Waiting for the login screen window to load"):
        main_win = h.get_main_window()

    with allure.step("Entering User ID (" + config.USER_ID + ")"):
        user_field = main_win.child_window(auto_id="userName", control_type="Edit")
        h.wait_and_click(user_field, timeout=25, desc="User ID field")
        user_field.type_keys(config.USER_ID, pause=0.05)
        time.sleep(1)

    with allure.step("Entering Password"):
        pass_field = main_win.child_window(auto_id="UserPassword", control_type="Edit")
        h.wait_and_click(pass_field, desc="Password field")
        pass_field.type_keys(config.PASSWORD, pause=0.05)
        time.sleep(1)

    with allure.step("Clicking the Login button"):
        login_btn = main_win.child_window(auto_id="btnLogin", control_type="Button")
        h.wait_and_click(login_btn, desc="Login button")
        time.sleep(3)

    with allure.step("Waiting for the main screen to become ready after login"):
        main_win = h.get_main_window()

    with allure.step("Dismissing the 'Target Notification' popup with Ok if it appears (shown when the target is reached)"):
        h.dismiss_notification_popup(main_win)

    with allure.step("Checking that the Customer field is ready"):
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_until_ready(customer_field, timeout=10, poll_interval=0.3, desc="Customer field (post-login)")
        time.sleep(1)


def add_customer_and_items(main_win, customer, items):
    with allure.step("Searching for customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")

    for item in items:
        with allure.step("Adding item to cart: " + item):
            h.wait_and_click(item_search_box, desc="Item search box (item " + item + ")")
            item_search_box.type_keys("^a{BACKSPACE}" + item + "{ENTER}", pause=0.15)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after " + item + ")")
            time.sleep(0.8)

    return item_search_box


def do_offer_flow(main_win, discount_type, discount_value):
    with allure.step("Opening the Special Discount list via F4"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F4}")
        time.sleep(1.5)

    with allure.step("Selecting the 'Open' offer"):
        # Was labelled "Cost Guard" in the UI; confirmed live (2026-09-02)
        # the display label changed to "Open" - matches the auto_ids used
        # below (OpenDiscountSelection/OpenDiscountValue/OpenDiscountAddButton),
        # which already used "Open" as the internal name even when the
        # visible label still said "Cost Guard".
        cost_guard = main_win.child_window(title="Open", control_type="ListItem")
        h.wait_and_click(cost_guard, desc="'Open' option")
        time.sleep(1.5)

    with allure.step("Selecting '" + discount_type + "' as the Discount Type"):
        discount_type_combo = main_win.child_window(auto_id="OpenDiscountSelection", control_type="ComboBox")
        h.wait_and_click(discount_type_combo, desc="Discount type combo")
        time.sleep(1)
        type_option = main_win.child_window(title=discount_type, control_type="ListItem")
        h.wait_and_click(type_option, desc="'" + discount_type + "' option")
        time.sleep(1)

    with allure.step("Entering the Discount Value (" + discount_value + ")"):
        discount_value_field = main_win.child_window(auto_id="OpenDiscountValue", control_type="Edit")
        h.wait_and_click(discount_value_field, desc="Discount value field")
        discount_value_field.type_keys(discount_value, pause=0.1)
        time.sleep(1)

    with allure.step("Clicking the Offer Add button"):
        add_button = main_win.child_window(auto_id="OpenDiscountAddButton", control_type="Button")
        h.wait_and_click(add_button, desc="Offer Add button")
        time.sleep(1.5)


def do_hold_and_recall(main_win, item_search_box):
    with allure.step("Holding the invoice via F9"):
        h.wait_until_ready(item_search_box, timeout=5, poll_interval=0.3, desc="Item search box (before hold)")
        time.sleep(0.5)
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2)

    def retry_f9():
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2)

    with allure.step("Dismissing the Hold confirmation popup (with retry)"):
        # This popup's shape has changed between app builds three times now:
        #   * older builds ask "Do you want to print a hold invoice token?"
        #     (Yes=PrimaryButton, No=SecondaryButton - No is clicked so a real
        #     print action cannot steal focus and break the F10 recall below)
        #   * a later build simplified it to a single "Hold Successfully" OK
        #     button, still PrimaryButton
        #   * build 5.0.2.0 keeps that single OK but moved it to CloseButton,
        #     which is what broke this step on 2026-10-27 - the wait found
        #     neither of the first two, left the popup open, and every step
        #     after it failed in turn.
        # SecondaryButton stays first so the deliberate "decline printing"
        # choice still wins on builds where both exist.
        h.wait_and_click_first_available(
            main_win,
            auto_ids=["SecondaryButton", "PrimaryButton", "CloseButton"],
            control_type="Button",
            timeout=6,
            retries=3,
            retry_action=retry_f9,
            desc="Hold confirmation popup"
        )
        time.sleep(1.5)

    with allure.step("Opening the Recall list and completing the Recall (with retry)"):
        # main_win.set_focus() is called again before each keystroke below
        # (not just once at the start) because focus can drift away from the
        # app between steps (popup animations, background activity), which
        # silently sends F10/Ctrl+End/Enter to the wrong window - previously
        # this had no verification, so a lost-focus recall failed silently
        # and only surfaced later as a confusing failure in Exchange/Payment.
        recalled = False
        for attempt in range(1, 4):
            main_win.set_focus()
            time.sleep(0.5)
            send_keys("{F10}")
            time.sleep(2)

            main_win.set_focus()
            time.sleep(0.3)
            send_keys("^{END}")
            time.sleep(0.5)

            main_win.set_focus()
            time.sleep(0.3)
            send_keys("{ENTER}")
            time.sleep(2.5)

            # The item search box exists on the Sale page whether or not
            # anything was actually recalled, so it cannot prove recall
            # succeeded. The ItemGrid having a row (and a non-zero total)
            # is the real signal that the held invoice actually came back.
            item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
            rows = item_grid.children(title="row", control_type="DataItem")
            if len(rows) > 0:
                recalled = True
                break
            print("Recall does not appear to have completed (cart still empty), attempt " + str(attempt) + "/3, retrying F10 -> Ctrl+End -> Enter...")

        if not recalled:
            raise Exception("Recall did not complete after 3 attempts (cart still empty after Ctrl+End + Enter)")


def do_exchange(main_win, invoice_no, new_item_barcodes):
    with allure.step("Opening the Exchange (F5) screen"):
        popup_open = False
        for attempt in range(1, 6):
            try:
                main_win.set_focus()
                time.sleep(0.5)
                send_keys("{F5}")
                time.sleep(2)
                exchange_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
                exchange_popup.wait('visible', timeout=4)
                popup_open = True
                break
            except Exception as e:
                print("Exchange popup has not appeared yet (attempt " + str(attempt) + "/5), pressing F5 again... (" + str(e) + ")")
                time.sleep(1)
        if not popup_open:
            raise Exception("Exchange popup did not open")

    with allure.step("Searching for invoice: " + invoice_no):
        exchange_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
        search_invoice_group = exchange_popup.child_window(auto_id="ExchangeInvoiceSearchBox", control_type="Group")
        search_invoice_box = search_invoice_group.child_window(auto_id="TextBox", control_type="Edit")
        search_invoice_box.click_input()
        search_invoice_box.type_keys(invoice_no + "{ENTER}", pause=0.05)
        time.sleep(2)

        initial_count = h.wait_for_stable_row_count(main_win, timeout=8)
        if initial_count <= 0:
            raise Exception("No products loaded after searching the invoice")

    with allure.step("Selecting the most recent item in the grid via Ctrl+End"):
        _, item_grid, _ = h.get_exchange_grid_rows(main_win)
        item_grid.click_input()
        time.sleep(0.5)
        send_keys("^{END}")
        time.sleep(1)
        h.wait_for_stable_row_count(main_win, timeout=5)
        time.sleep(0.5)

    with allure.step("Clicking the exchange row to add the item to the sales screen"):
        success = h.select_and_click_latest_row(main_win, max_retries=4)
        if not success:
            raise Exception("Clicking the exchange row was not successful")

    with allure.step("Closing the Exchange popup if it is still open"):
        try:
            exchange_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
            if exchange_popup.exists() and exchange_popup.is_visible():
                close_btn = exchange_popup.child_window(auto_id="conExchangeClose", control_type="Button")
                close_btn.wait('visible', timeout=5)
                h.press_button_robust(close_btn, desc="Exchange Close button")
                time.sleep(1.5)
        except Exception as e:
            print("Problem handling the Close button: " + str(e))

    with allure.step("Adding the new item(s) after exchange: " + str(new_item_barcodes)):
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")

        for barcode in new_item_barcodes:
            h.wait_until_ready(item_search_box, timeout=8, poll_interval=0.3, desc="Item search box (before " + barcode + ")")
            item_search_box.click_input()
            item_search_box.type_keys("^a{BACKSPACE}" + barcode + "{ENTER}", pause=0.05)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after " + barcode + ")")
            time.sleep(1.2)

        return item_search_box


def do_return(main_win, invoice_no):
    with allure.step("Clicking the Return button"):
        popup_open = False
        for attempt in range(1, 6):
            try:
                main_win.set_focus()
                time.sleep(0.5)
                return_btn = main_win.child_window(auto_id="btnReturn", control_type="Button")
                return_btn.wait('visible', timeout=6)
                return_btn.click_input()
                time.sleep(2)
            except Exception as e:
                print("Problem clicking the Return button: " + str(e))
                time.sleep(1)
                continue
            try:
                return_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
                return_popup.wait('visible', timeout=4)
                popup_open = True
                break
            except Exception:
                print("Return popup has not appeared yet (attempt " + str(attempt) + "/5), retrying...")
                time.sleep(1)
        if not popup_open:
            raise Exception("Return popup did not open")

    with allure.step("Searching for invoice: " + invoice_no):
        return_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
        search_invoice_group = return_popup.child_window(auto_id="ExchangeInvoiceSearchBox", control_type="Group")
        search_invoice_box = search_invoice_group.child_window(auto_id="TextBox", control_type="Edit")
        search_invoice_box.click_input()
        search_invoice_box.type_keys(invoice_no + "{ENTER}", pause=0.05)
        time.sleep(2)

        initial_count = h.wait_for_stable_row_count(main_win, timeout=8)
        if initial_count <= 0:
            raise Exception("No products loaded after searching the invoice")

    with allure.step("Selecting the most recent item in the grid via Ctrl+End"):
        _, item_grid, _ = h.get_exchange_grid_rows(main_win)
        item_grid.click_input()
        time.sleep(0.5)
        send_keys("^{END}")
        time.sleep(1)
        h.wait_for_stable_row_count(main_win, timeout=5)
        time.sleep(0.5)

    with allure.step("Clicking the return row to add the item to the sales screen"):
        success = h.select_and_click_latest_row(main_win, max_retries=4)
        if not success:
            raise Exception("Clicking the return row was not successful")

    with allure.step("Closing the Return popup if it is still open"):
        try:
            return_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
            if return_popup.exists() and return_popup.is_visible():
                close_btn = return_popup.child_window(auto_id="conExchangeClose", control_type="Button")
                close_btn.wait('visible', timeout=5)
                h.press_button_robust(close_btn, desc="Return Close button")
                time.sleep(1.5)
        except Exception as e:
            print("Problem handling the Close button: " + str(e))

    # No new item needs to be added for Return - the cursor stays on the cash amount field by default
    time.sleep(1.5)


def do_payment_and_close(main_win, item_search_box=None, skip_item_box=False):
    if not skip_item_box and item_search_box is not None:
        with allure.step("Moving from item search to the Cash Amount field"):
            main_win.set_focus()
            h.wait_and_click(item_search_box, desc="Item search box (final)")
            time.sleep(0.5)
            send_keys("{ENTER}")
            time.sleep(2)

    with allure.step("Confirming the Cash Amount (this sets the Paid Amount)"):
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        h.wait_and_click(cash_field, desc="Cash Amount field")
        time.sleep(1)
        send_keys("{ENTER}")
        time.sleep(2)

    with allure.step("Triggering Print (confirmation popup will appear)"):
        main_win.set_focus()
        send_keys("{ENTER}")
        time.sleep(2)

    with allure.step("Clicking 'No' on the Print popup (this generates the invoice)"):
        # Larger invoices (e.g. the 9-item Hold & Recall transaction) take longer
        # to generate before this popup appears, so this waits longer than a
        # typical 1-3 item transaction needs; wait_and_click returns as soon as
        # the button is visible, so this doesn't slow down the normal case.
        no_button = main_win.child_window(auto_id="SecondaryButton", control_type="Button")
        h.wait_and_click(no_button, timeout=30, desc="Print popup 'No' button")
        time.sleep(1.5)

    with allure.step("Confirming the 'Invoice Created Successfully' popup with OK/Enter"):
        send_keys("{ENTER}")
        time.sleep(2)


def do_logout(main_win):
    with allure.step("Focusing the window"):
        main_win.set_focus()
        time.sleep(1)

    with allure.step("Opening the Logout popup via Alt+L"):
        send_keys("%l")
        time.sleep(2)

    with allure.step("Clicking the Logout button"):
        logout_btn = main_win.child_window(auto_id="PrimaryButton", control_type="Button")
        h.wait_and_click(logout_btn, desc="Logout button")
        time.sleep(1.5)


def close_app(main_win):
    def retry_click_close():
        main_win.set_focus()
        time.sleep(0.5)

    with allure.step("Clicking the cross (X) button on the login screen after logout"):
        main_win.set_focus()
        h.wait_and_click_with_retry(
            main_win, auto_id="_CloseButton", control_type="Button",
            timeout=10, retries=3, retry_action=retry_click_close, desc="App Close (X) button"
        )
        time.sleep(1)

    with allure.step("Clicking Close on the 'Are you sure you want to close application?' popup"):
        # wait_and_click_with_retry absorbs the transient pywinauto/UIA
        # COMError that can otherwise leave the app stuck on this popup.
        h.wait_and_click_with_retry(
            main_win, auto_id="PrimaryButton", control_type="Button",
            timeout=10, retries=3, retry_action=retry_click_close, desc="Confirm Close button"
        )
        time.sleep(1)
