# ============================================================
# NEGATIVE BUSINESS ACTIONS - built on pos_helpers (generic,
# app-agnostic) and, where a full sale needs to actually be
# attempted, reuses pos_actions.do_payment_and_close as-is
# (called, never modified) - the happy-path flow itself stays
# untouched.
# ============================================================

import time
import allure
from pywinauto.keyboard import send_keys

import pos_helpers as h
import pos_actions as a

# auto_id of the "Ok" button on the "Login Failed" popup - confirmed by
# dumping the live control tree with print_control_identifiers() (it is
# CloseButton, NOT PrimaryButton like the Hold/Logout/Return popups in
# pos_actions.py, and NOT _CloseButton like the app's own title-bar X button).
ERROR_POPUP_OK_AUTO_ID = "CloseButton"


def _has_screen_text(main_win, needle):
    """True if any Text control currently on screen contains `needle`
    (case-insensitive). Used to detect popups by their message when the OK
    button's auto_id is not a reliable signal across app builds."""
    needle = needle.lower()
    try:
        for t in main_win.descendants(control_type="Text"):
            try:
                if needle in (t.window_text() or "").lower():
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _complete_sale_with_duplicate_retry(main_win, item_search_box, retries=3):
    """
    Wraps pos_actions.do_payment_and_close() with resilience against a real
    app guard: "Please wait 30 seconds before repeating this action"
    (auto_id "PrimaryButton") - this fires when a sale with the same
    customer/item/amount is repeated too quickly, which the discount tests
    are especially prone to since they intentionally reuse the same
    discounted item/customer across several cases in a row.

    Checking for that popup can itself hit the transient pywinauto/UIA
    COMError ("event was unable to invoke any of the subscribers") seen
    throughout this app's automation - if the CHECK fails, that must not
    crash out of the retry loop uncaught (this previously left the whole
    app closed/unresponsive for every test after it). So: on any payment
    failure, try to detect+dismiss the popup, but retry regardless of
    whether that detection itself succeeds, fails, or finds nothing - the
    item is still in the cart at that point, so retrying is always safe.
    """
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            a.do_payment_and_close(main_win, item_search_box)
            return
        except Exception as payment_error:
            last_error = payment_error
            try:
                # Whatever popup blocked the sale - the "Please wait 30 seconds"
                # duplicate-action guard, a print/confirm prompt, a customer or
                # amount warning - just dismiss whatever is up and retry. The
                # item is still in the cart at this point, so a retry is always
                # safe, and dismiss_any_popup is robust to the OK button's
                # auto_id drift between builds (PrimaryButton vs CloseButton).
                closed = h.dismiss_any_popup(main_win)
                print(
                    "Payment attempt %d/%d failed; dismissed %d popup(s), retrying... (%s)"
                    % (attempt, retries, closed, str(payment_error)[:80])
                )
            except Exception as check_error:
                print(
                    "Could not check/dismiss popups (attempt " + str(attempt) + "/" +
                    str(retries) + "): " + str(check_error)
                )
            time.sleep(5)
    raise Exception("Payment still did not complete after " + str(retries) + " retries: " + str(last_error))


def attempt_login(user_id, password):
    """
    Attempts a login with the given (possibly invalid) credentials.
    Returns True if the login was correctly REJECTED (error popup shown,
    or still on the login screen), False if it unexpectedly succeeded.
    Leaves the app back on a clean login screen either way, so the next
    negative case (or a happy-path run) can start fresh.
    """
    with allure.step("Waiting for the login screen window to load"):
        main_win = h.get_main_window()

    with allure.step("Entering User ID: '" + user_id + "'"):
        user_field = main_win.child_window(auto_id="userName", control_type="Edit")
        h.wait_and_click(user_field, timeout=25, desc="User ID field")
        if user_id:
            user_field.type_keys(user_id, pause=0.05)
        time.sleep(1)

    with allure.step("Entering Password: '" + ("*" * len(password)) + "'"):
        pass_field = main_win.child_window(auto_id="UserPassword", control_type="Edit")
        h.wait_and_click(pass_field, desc="Password field")
        if password:
            pass_field.type_keys(password, pause=0.05)
        time.sleep(1)

    with allure.step("Clicking the Login button"):
        # wait_and_click_with_retry absorbs the transient pywinauto/UIA
        # COMError ("event was unable to invoke any of the subscribers")
        # that can happen right after typing into the fields, by retrying.
        h.wait_and_click_with_retry(
            main_win, auto_id="btnLogin", control_type="Button",
            timeout=8, retries=3, desc="Login button"
        )
        time.sleep(3)

    with allure.step("Checking that login was rejected (error popup or still on login screen)"):
        login_rejected = _dismiss_error_popup_if_present(main_win) or _still_on_login_screen(main_win)

    with allure.step("Resetting the login fields for the next case"):
        _clear_login_fields(main_win)

    return login_rejected


def _dismiss_error_popup_if_present(main_win, auto_id=ERROR_POPUP_OK_AUTO_ID, retries=3):
    """Clicks the popup's OK button every time it appears. Retries on the
    transient UIA COMError instead of giving up after a single failed click,
    and re-checks that the popup actually disappeared before returning."""
    ok_btn = main_win.child_window(auto_id=auto_id, control_type="Button")
    if not ok_btn.exists(timeout=3):
        return False

    for attempt in range(1, retries + 1):
        try:
            h.press_button_robust(ok_btn, desc="Login error popup OK button")
        except Exception as e:
            print("OK click attempt " + str(attempt) + "/" + str(retries) + " raised: " + str(e))
        time.sleep(1)
        if not ok_btn.exists(timeout=2):
            return True
        print("Popup still visible after OK click attempt " + str(attempt) + "/" + str(retries) + ", retrying...")

    return True


def _still_on_login_screen(main_win):
    user_field = main_win.child_window(auto_id="userName", control_type="Edit")
    return user_field.exists(timeout=2)


def _clear_login_fields(main_win):
    for auto_id in ("userName", "UserPassword"):
        field = main_win.child_window(auto_id=auto_id, control_type="Edit")
        if field.exists(timeout=2):
            field.click_input()
            field.type_keys("^a{DELETE}")


def attempt_add_invalid_item(customer, item_barcode):
    """
    Tries to add an item using a barcode that doesn't exist in the system.
    Returns True if the app correctly rejected it (the item was NOT added
    to the cart), False if it was somehow added anyway.

    A "barcode not found" popup appears after the search Enter, and a
    second Enter dismisses it - that second Enter is sent explicitly below
    instead of relying on the search Enter to also clear the popup.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Searching for non-existent item barcode: " + item_barcode):
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        time.sleep(1.5)

    with allure.step("Dismissing the 'barcode not found' popup with Enter"):
        main_win.set_focus()
        send_keys("{ENTER}")
        time.sleep(1.5)

    with allure.step("Checking the item was not added to the cart"):
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        item_not_added = len(rows) == 0

    with allure.step("Clearing the customer and item fields for whatever runs next"):
        # Leaving the customer field with leftover text is dangerous: whatever
        # runs next (e.g. a positive transaction) types its own customer on
        # top of it (e.g. "123" + "123" = "123123"), which the app treats as
        # an invalid customer - and it was observed to silently let the sale
        # complete anyway with an EMPTY customer after that popup got
        # dismissed. Always leave both fields empty, not just the item box.
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        if customer_field.exists(timeout=2):
            customer_field.click_input()
            customer_field.type_keys("^a{DELETE}")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        if item_search_box.exists(timeout=2):
            item_search_box.click_input()
            item_search_box.type_keys("^a{DELETE}")

    return item_not_added


def attempt_sell_with_invalid_customer(customer, item_barcode, valid_customer):
    """
    Enters an invalid/non-existent customer, dismisses the resulting
    'invalid customer' popup by clicking OK, then still goes ahead and
    tries to add an item and complete a full sale anyway (to see whether
    the app actually blocks it, rather than defensively stopping early).
    Returns True if the sale was correctly BLOCKED, False if it went
    through anyway. Either way, finishes by entering a valid customer and
    completing the sale for real, so state stays clean for whatever runs
    next in the same flow.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for invalid customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Closing the 'No Customer Found' popup FIRST (before touching anything else)"):
        # The popup MUST be fully closed before adding the item - otherwise the
        # barcode gets typed while the modal is still on top and goes nowhere
        # (the app looked like it "went to transaction without closing the
        # popup"). The OK button's auto_id has drifted between builds
        # (PrimaryButton <-> CloseButton), so dismiss it the robust way, and
        # wait until no dialog button is left on screen.
        time.sleep(1)
        h.dismiss_any_popup(main_win)
        for _ in range(8):
            if not any(main_win.child_window(auto_id=aid, control_type="Button").exists(timeout=0)
                       for aid in h.POPUP_BUTTON_AUTO_IDS):
                break
            h.dismiss_any_popup(main_win)
            time.sleep(0.5)
        time.sleep(1)

    with allure.step("Now (popup closed) adding the item with Enter: " + item_barcode):
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        before = len(item_grid.children(title="row", control_type="DataItem"))
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)
        # If it did not land (a popup had eaten the first attempt), clear and retry once.
        if len(item_grid.children(title="row", control_type="DataItem")) == before:
            h.dismiss_any_popup(main_win)
            h.wait_and_click(item_search_box, desc="Item search box (retry)")
            item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
            time.sleep(1.5)

    with allure.step("Trying to confirm the Cash Amount / trigger Print anyway"):
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        h.wait_and_click(cash_field, desc="Cash Amount field")
        time.sleep(1)
        send_keys("{ENTER}")
        time.sleep(2)
        main_win.set_focus()
        send_keys("{ENTER}")
        time.sleep(2)

    with allure.step("Checking whether a 'customer not found' popup blocked the sale (fast check, no 30s wait)"):
        # Since the customer field is empty (cleared above), the payment
        # attempt just above can ALSO trigger a "Customer Information Not
        # Found" popup (a second, separate occurrence from the earlier "No
        # Customer Found !" one). Checking for it directly here - instead
        # of blindly calling pos_actions.do_payment_and_close() and letting
        # its 30s wait_and_click for the print button time out first - finds
        # the block in ~5s instead of ~30s.
        blocked_popup = (any(main_win.child_window(auto_id=aid, control_type="Button").exists(timeout=1)
                             for aid in h.POPUP_BUTTON_AUTO_IDS)
                         or _has_screen_text(main_win, "Customer Information Not Found"))
        if blocked_popup:
            h.dismiss_any_popup(main_win)
            time.sleep(1.5)
            sale_completed = False
        else:
            with allure.step("No block popup appeared - trying to finish via the normal Print confirmation"):
                sale_completed = True
                try:
                    no_button = main_win.child_window(auto_id="SecondaryButton", control_type="Button")
                    h.wait_and_click(no_button, timeout=10, desc="Print popup 'No' button")
                    time.sleep(1.5)
                    send_keys("{ENTER}")
                    time.sleep(2)
                except Exception as e:
                    print("Print confirmation did not appear either (app may have blocked it another way): " + str(e))
                    sale_completed = False

    if sale_completed:
        with allure.step("Confirming the cart actually cleared (payment really went through)"):
            item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
            rows = item_grid.children(title="row", control_type="DataItem")
            sale_completed = len(rows) == 0

    if not sale_completed:
        with allure.step("Completing the sale for real with a valid customer, so state stays clean"):
            item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
            if len(item_grid.children(title="row", control_type="DataItem")) > 0:
                customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
                h.wait_and_click(customer_field, desc="Customer field")
                customer_field.type_keys("^a{DELETE}")
                customer_field.type_keys("^a{BACKSPACE}" + valid_customer + "{ENTER}", pause=0.15)
                time.sleep(2)
                item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
                _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return not sale_completed


def attempt_underpay_then_correct(customer, items):
    """
    Adds a customer + items, then intentionally pays LESS than the actual
    Total Bill. The app shows a "Receive amount is less than Sale Amount"
    popup (Ok = auto_id "PrimaryButton", confirmed via
    print_control_identifiers()) - this dismisses it with Enter, then
    completes the sale for real with the exact total amount. After the
    dismiss-Enter, the app was observed to sometimes jump straight to the
    "Would you like to print?" confirmation on its own and sometimes stay
    on the Cash Amount field - both are handled below rather than assuming
    one specific path.

    Returns True if the underpayment was correctly rejected AND the retry
    with the exact amount then completed the sale, False otherwise.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

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
            h.wait_and_click(item_search_box, desc="Item search box (" + item + ")")
            item_search_box.type_keys("^a{BACKSPACE}" + item + "{ENTER}", pause=0.15)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after " + item + ")")
            time.sleep(0.8)

    with allure.step("Reading the actual Total Bill"):
        total_bill_el = main_win.child_window(auto_id="TextBoxTotalBill", control_type="Text")
        total_amount = int(float(total_bill_el.window_text()))

    underpay_amount = max(total_amount - 10, 1)

    with allure.step("Paying LESS than the actual total: " + str(underpay_amount) + " instead of " + str(total_amount)):
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        h.wait_and_click(cash_field, desc="Cash Amount field")
        cash_field.type_keys("^a{DELETE}")
        cash_field.type_keys(str(underpay_amount), pause=0.05)
        time.sleep(1)
        send_keys("{ENTER}")
        time.sleep(2)
        main_win.set_focus()
        send_keys("{ENTER}")
        time.sleep(2)

    with allure.step("Checking the 'Receive amount is less than Sale Amount' popup appeared, dismissing by clicking OK"):
        # This popup appears after the pay trigger and its OK button is auto_id
        # "CloseButton" in build 5.0.2.0 (NOT PrimaryButton) - confirmed live by
        # its text "Receive amount is less than Sale Amount". Detect by that
        # button OR the text, dismiss with a click (Enter is unreliable here),
        # and wait until it is really gone before retrying.
        underpay_rejected = (
            main_win.child_window(auto_id="CloseButton", control_type="Button").exists(timeout=4)
            or _has_screen_text(main_win, "Receive amount is less than")
        )
        if underpay_rejected:
            h.dismiss_any_popup(main_win)
            for _ in range(8):
                if not _has_screen_text(main_win, "Receive amount is less than"):
                    break
                h.dismiss_any_popup(main_win)
                time.sleep(0.5)
        time.sleep(1.5)

    with allure.step("Retrying with the exact total amount"):
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        if cash_field.exists(timeout=4):
            h.wait_and_click(cash_field, desc="Cash Amount field (retry)")
            cash_field.type_keys("^a{DELETE}")
            cash_field.type_keys(str(total_amount), pause=0.05)
            time.sleep(1)
            send_keys("{ENTER}")
            time.sleep(2)
            main_win.set_focus()
            send_keys("{ENTER}")
            time.sleep(2)

    with allure.step("Clicking 'No' on the Print popup (this generates the invoice)"):
        no_button = main_win.child_window(auto_id="SecondaryButton", control_type="Button")
        if no_button.exists(timeout=20):
            h.wait_and_click(no_button, timeout=20, desc="Print popup 'No' button")
            time.sleep(1.5)
        else:
            # No explicit "No" button on this build's path - dismiss whatever
            # print/confirm popup is up so the invoice still gets created.
            h.dismiss_any_popup(main_win)
            time.sleep(1)

    with allure.step("Confirming the 'Invoice Created Successfully' popup"):
        send_keys("{ENTER}")
        time.sleep(1)
        h.dismiss_any_popup(main_win)
        time.sleep(2)

    with allure.step("Confirming the sale completed with the correct amount"):
        # Checking ItemGrid immediately after confirming the "Invoice
        # Created Successfully" popup was found live to sometimes catch
        # the screen before it finished clearing back to an empty cart -
        # the sale had genuinely already completed (Print/Invoice popups
        # don't appear otherwise), just not yet reflected in the grid.
        # Retrying for a couple seconds instead of checking once fixes
        # this false negative.
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        sale_completed = False
        for attempt in range(5):
            rows = item_grid.children(title="row", control_type="DataItem")
            if len(rows) == 0:
                sale_completed = True
                break
            time.sleep(0.5)

    return underpay_rejected and sale_completed


def attempt_sell_without_customer(item_barcodes, valid_customer):
    """
    Adds one or more items WITHOUT entering any customer, then tries to
    confirm payment. The app shows a "Customer Information Not Found"
    popup (Ok = auto_id "PrimaryButton", confirmed via
    print_control_identifiers()) - dismisses it with a direct click (Enter
    alone was found unreliable for this app's customer-related popups -
    see the "No Customer Found !" popup in attempt_sell_with_invalid_customer)
    and checks the sale did NOT complete (the item(s) are still in the
    cart). Then enters a valid customer and finishes the sale for real, so
    state stays clean for whatever runs next.

    item_barcodes may be a single barcode string or a list of barcodes.

    Returns True if the sale was correctly blocked without a customer,
    False if it went through anyway.
    """
    if isinstance(item_barcodes, str):
        item_barcodes = [item_barcodes]

    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    for item_barcode in item_barcodes:
        with allure.step("Adding an item without entering any customer: " + item_barcode):
            h.wait_and_click(item_search_box, desc="Item search box")
            item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after " + item_barcode + ")")
            time.sleep(1.5)

    with allure.step("Confirming the item(s) actually landed in the cart before testing the no-customer block"):
        # The whole point of this case is "can a sale go through with NO
        # customer" - which is only a real test if the item is in the cart
        # first. The add was observed to silently miss (a leftover barcode in
        # the search box got concatenated into an invalid code, so nothing was
        # added) and the flow then went to payment on an EMPTY cart, which is
        # not what this case is meant to check. So: if the cart is empty,
        # re-add each barcode once (box cleared first), and if it is STILL
        # empty, fail loudly rather than "blocking" a sale that had nothing.
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        if len(item_grid.children(title="row", control_type="DataItem")) == 0:
            for item_barcode in item_barcodes:
                h.wait_and_click(item_search_box, desc="Item search box (re-add " + item_barcode + ")")
                item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
                h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (re-add after " + item_barcode + ")")
                time.sleep(1.5)
        rows_before_pay = item_grid.children(title="row", control_type="DataItem")
        assert len(rows_before_pay) > 0, (
            "No item could be added to the cart, so the no-customer block cannot be "
            "tested (barcodes: %s)" % (item_barcodes,))

    with allure.step("Trying to confirm the Cash Amount / trigger Print without a customer"):
        # Triggering the pay/print path takes TWO Enters in this build: the
        # first confirms the Cash Amount, the second actually starts the
        # print - and only THEN does the app check for a customer. A single
        # Enter produces no popup at all (confirmed live), which is why an
        # earlier version saw "no block".
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        h.wait_and_click(cash_field, desc="Cash Amount field")
        time.sleep(1)
        send_keys("{ENTER}")
        time.sleep(2)
        main_win.set_focus()
        send_keys("{ENTER}")
        time.sleep(2)

    with allure.step("Checking the 'Customer Information Not Found' popup appeared, dismissing by clicking OK"):
        # This popup's OK button is auto_id "CloseButton" in build 5.0.2.0
        # (NOT "PrimaryButton" - the OK moved, same as the Hold popup did);
        # confirmed live by its on-screen text "Customer Information Not
        # Found". Detect by that button OR the text, then dismiss by clicking
        # OK (a direct click, since Enter is unreliable on this app's
        # customer popups) and wait until it is really gone.
        ok_btn = main_win.child_window(auto_id="CloseButton", control_type="Button")
        popup_appeared = ok_btn.exists(timeout=4) or _has_screen_text(main_win, "Customer Information Not Found")
        if popup_appeared:
            if ok_btn.exists(timeout=1):
                h.press_button_robust(ok_btn, desc="Customer Information Not Found OK button")
            else:
                send_keys("{ESC}")
            # wait for the popup to actually close before touching anything else
            for _ in range(10):
                if not ok_btn.exists(timeout=1) and not _has_screen_text(main_win, "Customer Information Not Found"):
                    break
                time.sleep(0.5)
        time.sleep(1)

    with allure.step("Confirming the sale was blocked (item still in the cart)"):
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        sale_blocked = len(rows) > 0

    with allure.step("Completing the sale for real: close popup, enter customer + Enter, THEN sell"):
        # Order matters (and was getting out of sequence): the popup must be
        # fully closed FIRST, then the customer entered AND confirmed with its
        # own Enter, and only after the customer is accepted do we complete the
        # transaction. Typing the customer while the popup was still up, or
        # letting the sale proceed before the customer's Enter registered, was
        # sending the flow back into the transaction with no customer set.
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}", pause=0.1)      # clear any leftover
        customer_field.type_keys(valid_customer, pause=0.12)      # type the number
        time.sleep(0.4)
        send_keys("{ENTER}")                                      # confirm with its OWN Enter
        time.sleep(2)
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return popup_appeared and sale_blocked


def verify_discount_applied_for_group_customer(
    customer, items, expected_total_bill, expected_total_discount, expected_grand_total
):
    """
    Adds a customer who IS in the discounted group plus one or more items
    that have an active group discount, and checks the discount actually
    applies correctly (TotalBill/TextBoxTotalDiscount/GrandTotal match the
    expected discounted values). This is the positive baseline check the
    other discount negative cases assume still holds. Completes the sale
    afterward, so state stays clean for whatever runs next.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer (in the discounted group): " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    for item_barcode in items:
        with allure.step("Adding discounted item: " + item_barcode):
            h.wait_and_click(item_search_box, desc="Item search box")
            item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after " + item_barcode + ")")
            time.sleep(1)

    with allure.step("Checking the discount was applied correctly"):
        total_bill = main_win.child_window(auto_id="TextBoxTotalBill", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        applied_correctly = (
            total_bill == expected_total_bill
            and total_discount == expected_total_discount
            and grand_total == expected_grand_total
        )

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return applied_correctly


def verify_discount_not_applied(customer, item_barcode, expected_full_price):
    """
    Adds a customer who is NOT in the discounted customer group, plus an
    item that DOES have an active customer-group discount for other
    customers, and checks that the full (non-discounted) price is charged
    instead of the discounted one. Completes the sale afterward either way
    so state stays clean for whatever runs next in the same flow.

    Returns True if no discount leaked through to this customer, False if
    it did (a real defect - the discount should be scoped to its group).
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer (outside the discounted group): " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Adding an item that has a group discount for other customers: " + item_barcode):
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Checking that no discount was applied"):
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        no_discount_leaked = (grand_total == expected_full_price) and (total_discount == "0.00")

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return no_discount_leaked


def verify_discount_hidden_without_customer(item_barcode, expected_full_price, cleanup_customer):
    """
    Adds a discounted item with NO customer entered and checks that the
    full (non-discounted) price is shown - the discount should not apply
    without a customer. Then enters a valid customer and completes the
    sale for real, so state stays clean for whatever runs next.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Adding a discounted item without any customer: " + item_barcode):
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Checking no discount is shown without a customer"):
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        no_discount_shown = (grand_total == expected_full_price) and (total_discount == "0.00")

    with allure.step("Completing the sale with a valid customer, so state stays clean"):
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{DELETE}")
        customer_field.type_keys(cleanup_customer + "{ENTER}", pause=0.15)
        time.sleep(2)
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return no_discount_shown


def verify_discount_updates_on_customer_switch(
    item_barcode, initial_customer, switch_to_customer, expected_discounted_total, expected_total_discount
):
    """
    Adds a discounted item under a customer who is NOT in the discounted
    group (full price), then switches the customer mid-cart to one who IS
    in the group, and checks whether the discount recalculates.

    Known defect (verified live 2026-08-13): the discount does NOT
    recalculate when the customer changes after an item is already in the
    cart - GrandTotal/TextBoxTotalDiscount stay stale at whatever they were
    when the item was added. Returns True only if the app actually
    recalculated - the caller's assertion is expected to FAIL until the app
    is fixed to recalculate discounts on customer change. Completes the
    sale afterward either way, so state stays clean for whatever runs next.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for a customer outside the discount group: " + initial_customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + initial_customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    with allure.step("Adding the discounted item at full price: " + item_barcode):
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Switching to the discounted-group customer: " + switch_to_customer):
        # Clicking the field alone does NOT select/clear its existing text
        # in this app (confirmed earlier: typing on top of a leftover value
        # concatenates instead of replacing, e.g. "123" + "123" = "123123") -
        # so the old customer must be explicitly cleared before typing the
        # new one, or this ends up typing an invalid customer number.
        h.wait_and_click(customer_field, desc="Customer field (switch)")
        customer_field.type_keys("^a{DELETE}")
        customer_field.type_keys(switch_to_customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Checking whether the discount recalculated for the new customer"):
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        discount_recalculated = (grand_total == expected_discounted_total) and (total_discount == expected_total_discount)

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return discount_recalculated


def verify_discount_scales_with_quantity(
    customer, item_barcode, quantity, expected_total_bill, expected_total_discount, expected_grand_total
):
    """
    Adds the same discounted item multiple times (scanning the same barcode
    repeatedly increases quantity) and checks the discount scales
    proportionally with quantity rather than staying flat. Completes the
    sale afterward, so state stays clean for whatever runs next.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")

    for i in range(quantity):
        with allure.step("Scanning the discounted item (" + str(i + 1) + "/" + str(quantity) + "): " + item_barcode):
            h.wait_and_click(item_search_box, desc="Item search box (scan " + str(i + 1) + ")")
            item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
            h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after scan " + str(i + 1) + ")")
            time.sleep(1)

    with allure.step("Checking the discount scaled correctly with quantity"):
        total_bill = main_win.child_window(auto_id="TextBoxTotalBill", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        scaled_correctly = (
            total_bill == expected_total_bill
            and total_discount == expected_total_discount
            and grand_total == expected_grand_total
        )

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return scaled_correctly


def verify_discount_stacks_with_manual_offer(
    customer, item_barcode, offer_discount_type, offer_discount_value,
    expected_total_discount, expected_other_discount, expected_grand_total
):
    """
    Adds a discounted item under the discounted group's customer, then
    applies a manual "Cost Guard" F4 offer on top, and checks the two
    discounts stack (compound) correctly rather than conflicting or
    double-counting the same base amount. Completes the sale afterward.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    with allure.step("Adding the discounted item: " + item_barcode):
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Applying the manual Cost Guard offer: " + offer_discount_type + " " + offer_discount_value):
        a.do_offer_flow(main_win, offer_discount_type, offer_discount_value)

    with allure.step("Checking the two discounts stacked correctly"):
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        other_discount = main_win.child_window(auto_id="TextBoxOtherDiscount", control_type="Text").window_text()
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        stacked_correctly = (
            total_discount == expected_total_discount
            and other_discount == expected_other_discount
            and grand_total == expected_grand_total
        )

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return stacked_correctly


def _drain_all_holds(main_win, max_iterations=10):
    """
    Repeatedly recalls and pays off any pending held invoices until a
    recall attempt genuinely brings nothing back, so a "recall with zero
    holds" check can start from a guaranteed-empty hold queue instead of
    assuming no holds are left over from earlier/failed runs.
    """
    for _ in range(max_iterations):
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

        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        if len(rows) == 0:
            return
        print("Draining a leftover held invoice before the zero-holds check...")
        item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        try:
            _complete_sale_with_duplicate_retry(main_win, item_search_box)
        except Exception as e:
            print("Could not clear a leftover held invoice: " + str(e))
            return


def verify_recall_with_no_holds():
    """
    Drains any pre-existing held invoices first (so this starts from a
    guaranteed-empty hold queue, since repeated test runs could otherwise
    leave one behind), then recalls once more and checks the app handles
    an empty hold list safely.

    Verified live: F10 -> Ctrl+End -> Enter with zero pending holds is a
    safe no-op in this app (cart stays empty, no popup, no error).

    Returns True if it was a safe no-op, False if anything unexpected
    happened (a crash, an error popup, or - worse - a phantom/incorrect
    recall).
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Draining any pre-existing held invoices to guarantee an empty hold queue"):
        _drain_all_holds(main_win)

    with allure.step("Recalling with (now guaranteed) zero pending holds"):
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

    with allure.step("Confirming this was a safe no-op (no crash, cart stays empty)"):
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        total_bill = main_win.child_window(auto_id="TextBoxTotalBill", control_type="Text").window_text()
        safe_no_op = (len(rows) == 0) and (total_bill == "0.00")

    return safe_no_op


def attempt_hold_empty_cart():
    """
    Presses Hold (F9) with an empty cart (no customer, no items).

    Expected: the same "No item selected" popup that the on-screen Hold
    button shows for an empty cart.

    Verified live: clicking the Hold BUTTON correctly shows "No item
    selected", but the F9 shortcut instead shows "Hold Successfully (0)"
    - a success message for an action that held nothing. No phantom
    invoice is actually queued (recall stays empty), but the wrong popup
    is a defect in its own right, so this case FAILS on it.

    Returns True only if the "No item selected" popup appeared AND no
    phantom hold was queued. Returns False if the "Hold Successfully"
    popup appeared instead, or if a real empty hold got queued (a
    garbage invoice should never exist).
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Pressing Hold (F9) on an empty cart"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2.5)

    with allure.step("Reading which popup came up (expected: 'No item selected')"):
        popup_text = _read_visible_popup_text(main_win)
        print("Empty-cart Hold (F9) popup text: " + repr(popup_text))
        got_no_item_popup = "no item" in popup_text.lower()
        got_hold_success_popup = "hold successfully" in popup_text.lower()
        allure.attach(
            "Popup text: " + popup_text
            + "\n'No item selected' shown: " + str(got_no_item_popup)
            + "\n'Hold Successfully' shown: " + str(got_hold_success_popup),
            name="empty_cart_hold_popup", attachment_type=allure.attachment_type.TEXT,
        )

    with allure.step("Dismissing the popup"):
        for auto_id in ("PrimaryButton", ERROR_POPUP_OK_AUTO_ID):
            ok_btn = main_win.child_window(auto_id=auto_id, control_type="Button")
            if ok_btn.exists(timeout=3):
                h.press_button_robust(ok_btn, desc="Empty-cart Hold popup OK button")
                break
        time.sleep(1.5)

    with allure.step("Trying to recall - if nothing comes back, no phantom hold was actually queued"):
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

    with allure.step("Confirming no phantom hold was queued"):
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        no_phantom_hold = len(rows) == 0

    with allure.step("Verdict: 'No item selected' popup required, 'Hold Successfully' is a defect"):
        if got_hold_success_popup:
            print("DEFECT: F9 on an empty cart showed 'Hold Successfully' instead of 'No item selected'")
        elif not got_no_item_popup:
            print("DEFECT: F9 on an empty cart did not show the 'No item selected' popup")

    return got_no_item_popup and not got_hold_success_popup and no_phantom_hold


def _read_visible_popup_text(main_win):
    """Joins the text of every Text element currently under the main
    window. A WinUI ContentDialog (title + content) lives inside the main
    window's UIA tree, so this is a cheap way to read whatever popup is
    open without knowing its exact auto_ids."""
    texts = []
    try:
        for e in main_win.descendants(control_type="Text"):
            try:
                t = e.window_text().strip()
            except Exception:
                continue
            if t:
                texts.append(t)
    except Exception as e:
        print("Could not read popup text: " + str(e))
    return " | ".join(texts)


def verify_discount_survives_hold_recall(customer, item_barcode, expected_grand_total, expected_total_discount_after_recall):
    """
    Adds a discounted item under the discount-group customer, Holds it,
    then Recalls it, and checks the discount is still applied (GrandTotal
    stays discounted, not reset to full price).

    Verified live 2026-08-14: the discount amount survives Hold -> Recall
    correctly, but TextBoxTotalDiscount's FORMAT changes after a recall
    (e.g. "10.00" becomes "10" - numerically identical, a cosmetic quirk)
    - so this compares the discount numerically rather than as an exact
    string. Completes the sale afterward, so state stays clean for
    whatever runs next.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer (in the discounted group): " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    with allure.step("Adding the discounted item: " + item_barcode):
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Holding the discounted invoice (F9)"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2.5)
        # Hold confirmation OK = "CloseButton" on build 5.0.2.0 (it moved off
        # PrimaryButton); dismiss whatever Hold popup is up, robustly, so the
        # recall (F10) that follows is not blocked by a leftover modal.
        h.dismiss_any_popup(main_win)
        time.sleep(1.5)

    with allure.step("Recalling the held invoice (F10 -> Ctrl+End -> Enter)"):
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

    with allure.step("Checking the discount is still applied after recall"):
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        try:
            discount_matches = float(total_discount) == float(expected_total_discount_after_recall)
        except ValueError:
            discount_matches = False
        discount_survived = (grand_total == expected_grand_total) and discount_matches

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return discount_survived


def verify_discount_after_hold_recall_customer_switch(
    group_customer, other_customer, item_barcode,
    expected_grand_total_discounted, expected_total_discount_discounted,
    expected_grand_total_full_price
):
    """
    Adds a discounted item under the group customer, Holds it, Recalls it
    (discount intact), switches the customer to a non-group customer, then
    switches BACK to the group customer, checking the discount at each
    switch.

    Verified live 2026-08-14: switching AWAY from the group customer
    correctly REMOVES the discount (recalculation works for removal), but
    switching BACK does NOT re-apply it (stays at full price) -
    recalculation only works in the removal direction, not addition. A
    more precise variant of the general customer-switch defect (see
    verify_discount_updates_on_customer_switch), specific to the
    Hold->Recall context.

    Returns True only if the discount correctly reappeared after switching
    back to the group customer - expected to FAIL until the app fixes
    this. Completes the sale afterward regardless, so state stays clean.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for the group customer: " + group_customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + group_customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    with allure.step("Adding the discounted item: " + item_barcode):
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Holding the discounted invoice (F9)"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2.5)
        # Hold confirmation OK = "CloseButton" on build 5.0.2.0 (it moved off
        # PrimaryButton); dismiss whatever Hold popup is up, robustly, so the
        # recall (F10) that follows is not blocked by a leftover modal.
        h.dismiss_any_popup(main_win)
        time.sleep(1.5)

    with allure.step("Recalling the held invoice (F10 -> Ctrl+End -> Enter)"):
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

    with allure.step("Switching to a non-group customer: " + other_customer):
        h.wait_and_click(customer_field, desc="Customer field (switch to other)")
        customer_field.type_keys("^a{DELETE}")
        customer_field.type_keys(other_customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Checking the discount was removed for the non-group customer"):
        grand_total_after_switch_away = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        discount_removed_correctly = grand_total_after_switch_away == expected_grand_total_full_price

    with allure.step("Switching back to the group customer: " + group_customer):
        h.wait_and_click(customer_field, desc="Customer field (switch back)")
        customer_field.type_keys("^a{DELETE}")
        customer_field.type_keys("^a{BACKSPACE}" + group_customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    with allure.step("Checking the discount reappeared for the group customer"):
        grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
        total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
        try:
            discount_matches = float(total_discount) == float(expected_total_discount_discounted)
        except ValueError:
            discount_matches = False
        discount_reapplied = (grand_total == expected_grand_total_discounted) and discount_matches

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return discount_removed_correctly and discount_reapplied


def verify_no_double_recall(customer, item_barcode):
    """
    Holds an item, Recalls it, completes the sale (payment), then tries to
    Recall AGAIN right after - checking that the now-completed invoice is
    no longer available (correctly removed from the recall queue), so it
    cannot be recalled/sold a second time.

    Verified live 2026-08-14: after payment completes, a second recall
    attempt correctly comes back empty (ItemGrid rows=0, TextBoxTotalBill
    "0.00") - the app does not let you recall an already-completed
    invoice. Nothing to clean up afterward since the second recall found
    nothing.

    Returns True if the second recall was correctly empty (no double-
    recall), False if the same invoice came back (a real duplicate-sale
    risk).
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Searching for customer: " + customer):
        main_win.set_focus()
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
    with allure.step("Adding item: " + item_barcode):
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item_barcode + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)

    with allure.step("Holding the invoice (F9)"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2.5)
        # Hold confirmation OK = "CloseButton" on build 5.0.2.0 (it moved off
        # PrimaryButton); dismiss whatever Hold popup is up, robustly, so the
        # recall (F10) that follows is not blocked by a leftover modal.
        h.dismiss_any_popup(main_win)
        time.sleep(1.5)

    with allure.step("Recalling it the first time (F10 -> Ctrl+End -> Enter)"):
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

    with allure.step("Completing the sale (payment)"):
        item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    with allure.step("Trying to Recall the same invoice again"):
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

    with allure.step("Confirming the second recall found nothing (no double-recall)"):
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows = item_grid.children(title="row", control_type="DataItem")
        no_double_recall = len(rows) == 0

    return no_double_recall


def verify_recall_specific_invoice(
    before_customer, before_item, target_customer, target_item,
    target_offer_discount_type, target_offer_discount_value,
    after_customer, after_item
):
    """
    Holds THREE distinct invoices in order - a plain distractor first
    (oldest), then the TARGET invoice for the discounted-group customer
    with a discount item plus a manual Cost Guard (F4) offer stacked on
    top, then a second plain distractor (latest) - then recalls the
    TARGET (middle, non-latest) one specifically from the Recall list by
    clicking that row's body directly and pressing Enter.

    IMPORTANT: this deliberately does NOT click the row's
    "btnRecallInvoiceView" button - that was found to just discard the
    held invoice without loading it (it's a "view" affordance, not how you
    select a row for recall). The correct interaction is: click the row
    itself to select/highlight it, then press Enter - the same pattern as
    the existing Ctrl+End -> Enter recall, just with an explicit click
    instead of Ctrl+End to pick a specific (non-latest) row.

    Verified live 2026-08-14: this correctly restores the TARGET invoice's
    own customer/item, not the latest invoice's, even with a group
    discount + manual offer on the target itself.

    The target is always the second-to-last row in the Recall list at the
    moment this runs ("before" held first, target second, "after" third)
    - this holds regardless of how many older leftover holds from previous
    runs might also be in the list ahead of all three.

    Returns True if the correct (target) customer and item were restored,
    False otherwise. Completes the sale afterward, so state stays clean.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")

    def add_and_hold(customer, item, offer_discount_type=None, offer_discount_value=None):
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        h.wait_and_click(customer_field, desc="Customer field")
        customer_field.type_keys("^a{DELETE}")
        customer_field.type_keys("^a{BACKSPACE}" + customer + "{ENTER}", pause=0.15)
        time.sleep(2)
        h.wait_and_click(item_search_box, desc="Item search box")
        item_search_box.type_keys("^a{BACKSPACE}" + item + "{ENTER}", pause=0.15)
        h.wait_until_ready(item_search_box, timeout=6, poll_interval=0.3, desc="Item search box (after item)")
        time.sleep(1.5)
        if offer_discount_type and offer_discount_value:
            a.do_offer_flow(main_win, offer_discount_type, offer_discount_value)
            time.sleep(1)
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F9}")
        time.sleep(2.5)
        # Hold confirmation OK = "CloseButton" on build 5.0.2.0 (it moved off
        # PrimaryButton); dismiss whatever Hold popup is up, robustly, so the
        # recall (F10) that follows is not blocked by a leftover modal.
        h.dismiss_any_popup(main_win)
        time.sleep(1.5)

    with allure.step("Holding a distractor invoice (oldest): " + before_customer + " / " + before_item):
        add_and_hold(before_customer, before_item)

    with allure.step(
        "Holding the TARGET invoice, middle (group discount + manual offer): "
        + target_customer + " / " + target_item
    ):
        add_and_hold(target_customer, target_item, target_offer_discount_type, target_offer_discount_value)

    with allure.step("Holding a distractor invoice (latest): " + after_customer + " / " + after_item):
        add_and_hold(after_customer, after_item)

    with allure.step("Opening the Recall list and clicking the TARGET (middle, non-latest) row directly, then Enter"):
        main_win.set_focus()
        time.sleep(0.5)
        send_keys("{F10}")
        time.sleep(2.5)
        popup = main_win.child_window(auto_id="conRecallInvoice", control_type="Window")
        grid = popup.child_window(auto_id="ItemGridRecallInvoice", control_type="DataGrid")
        rows = grid.children(title="row", control_type="DataItem")
        target_row = rows[-2]
        target_row.click_input(coords=(300, 20))
        time.sleep(1)
        main_win.set_focus()
        time.sleep(0.3)
        send_keys("{ENTER}")
        time.sleep(2.5)

    with allure.step("Checking the correct (target) invoice was restored, not the latest"):
        customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
        recalled_customer = customer_field.window_text()
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        rows2 = item_grid.children(title="row", control_type="DataItem")
        recalled_item = None
        if rows2:
            cells = rows2[0].children()
            if len(cells) > 1:
                recalled_item = cells[1].window_text().strip()
        correct_invoice_restored = (recalled_customer == target_customer) and (recalled_item == target_item)

    with allure.step("Completing the sale so state stays clean for whatever runs next"):
        _complete_sale_with_duplicate_retry(main_win, item_search_box)

    return correct_invoice_restored


last_return_validation_results = {}   # filled by verify_return_quantity_validation, read by the test


def _find_qty_edit_near(container, target_rect, retries):
    """Shared retry helper for the Return popup's "Exc.Qty" cell and the
    main cart's "Quantity" cell - confirmed live that the inline edit
    control double-click brings up is a SEPARATE overlay element (not a
    transformation of the existing Text cell), positioned at the same
    rectangle, and is flaky to detect on the first attempt (control tree
    not always updated in time) - retrying a few times with a fresh
    descendants() search is what made this reliable."""
    for _ in range(retries):
        time.sleep(0.6)
        for e in container.descendants(control_type="Edit"):
            r = e.rectangle()
            if abs(r.left - target_rect.left) < 25 and abs(r.top - target_rect.top) < 25:
                return e
    return None


def verify_return_quantity_validation(
    customer, items, partial_return_item, partial_return_purchased_qty,
    over_return_attempt, partial_return_qty, cart_over_return_attempt,
    full_return_item, zero_qty_attempt, unchanged_items
):
    """
    Sells `items` (a flat barcode list - duplicates raise that line's
    quantity), then in Return:
      1. Double-clicks the "Exc.Qty" cell of `partial_return_item` (which
         was bought at `partial_return_purchased_qty`) and types
         `over_return_attempt` (more than purchased) - this must be
         rejected/reverted back to the purchased quantity, not accepted.
      2. Re-edits the same cell to the valid `partial_return_qty` (less
         than purchased) - a genuine partial return - and adds that row
         to the cart.
      3. Adds a full return of `full_return_item` (bought at qty 1) to
         the cart too.
      4. In the main cart, double-clicks `full_return_item`'s Quantity
         cell and types `zero_qty_attempt` ("0") - this must also be
         rejected/reverted (you cannot zero-out a return line this way).
         Also re-confirms `cart_over_return_attempt` is rejected on the
         partial-return line at the cart stage (a second, independent
         validation layer beyond step 1's popup-level check).
      5. Pays for the return, then reopens Return on the SAME invoice and
         confirms: `partial_return_item` shows exactly (purchased -
         partial_return_qty) remaining, `full_return_item` is GONE
         entirely (fully returned = no longer returnable), and every
         item in `unchanged_items` still shows its original quantity.

    Returns True only if every one of the above holds, False otherwise.
    """
    with allure.step("Waiting for the Sale screen to load"):
        main_win = h.get_main_window()

    with allure.step("Selling " + str(len(items)) + " item scans to customer: " + customer):
        item_search_box = a.add_customer_and_items(main_win, customer, items)
        _complete_sale_with_duplicate_retry(main_win, item_search_box)
        invoice_no = h.get_most_recent_invoice_no(main_win)

    def open_return_and_search():
        main_win.set_focus()
        time.sleep(0.5)
        return_btn = main_win.child_window(auto_id="btnReturn", control_type="Button")
        return_btn.click_input()
        time.sleep(2)
        popup, _, _ = h.get_exchange_grid_rows(main_win)
        search_group = popup.child_window(auto_id="ExchangeInvoiceSearchBox", control_type="Group")
        search_box = search_group.child_window(auto_id="TextBox", control_type="Edit")
        search_box.click_input()
        search_box.type_keys(invoice_no + "{ENTER}", pause=0.05)
        time.sleep(2)
        return h.get_exchange_grid_rows(main_win)

    def find_row(rows, barcode):
        for row in rows:
            cells = row.children()
            if cells[1].window_text() == barcode:
                return row
        return None

    def edit_exc_qty(popup, row, value):
        cells = row.children()
        exc_qty_cell = cells[4]
        target_rect = exc_qty_cell.rectangle()
        exc_qty_cell.double_click_input()
        edit = _find_qty_edit_near(popup, target_rect, retries=6)
        if edit is None:
            return False
        edit.click_input()
        edit.type_keys("^a{DELETE}")
        edit.type_keys(value, pause=0.1)
        time.sleep(0.5)
        send_keys("{ENTER}")
        time.sleep(1.5)
        return True

    over_return_blocked = False
    partial_return_accepted = False
    with allure.step(
        "Return popup: attempting to over-return " + partial_return_item +
        " (" + over_return_attempt + " vs " + partial_return_purchased_qty + " purchased)"
    ):
        popup, _, rows = open_return_and_search()
        target_row = find_row(rows, partial_return_item)
        if target_row is not None:
            edit_exc_qty(popup, target_row, over_return_attempt)
            popup, _, rows = h.get_exchange_grid_rows(main_win)
            target_row = find_row(rows, partial_return_item)
            exc_qty_after_overreach = target_row.children()[4].window_text() if target_row else ""
            over_return_blocked = exc_qty_after_overreach != over_return_attempt

    with allure.step(
        "Return popup: correcting to a valid partial return (" + partial_return_qty + ")"
    ):
        popup, _, rows = h.get_exchange_grid_rows(main_win)
        target_row = find_row(rows, partial_return_item)
        if target_row is not None:
            edit_exc_qty(popup, target_row, partial_return_qty)
            popup, _, rows = h.get_exchange_grid_rows(main_win)
            target_row = find_row(rows, partial_return_item)
            exc_qty_after_partial = target_row.children()[4].window_text() if target_row else ""
            partial_return_accepted = exc_qty_after_partial == partial_return_qty

    partial_return_added = False
    with allure.step("Adding the partial return to the cart"):
        popup, item_grid, rows = h.get_exchange_grid_rows(main_win)
        target_row = find_row(rows, partial_return_item)
        if target_row is not None:
            target_row.click_input(coords=(300, 20))
            time.sleep(1)
            # A single click selects but doesn't always confirm/add on a
            # non-last row (confirmed live) - if it's still present, fall
            # back to the retry-based confirm click, same as the
            # full-return step below.
            popup2, _, rows2 = h.get_exchange_grid_rows(main_win)
            if find_row(rows2, partial_return_item) is not None:
                h.select_and_click_latest_row(main_win, max_retries=4)
            time.sleep(1)
        popup3, _, rows3 = h.get_exchange_grid_rows(main_win)
        partial_return_added = find_row(rows3, partial_return_item) is None

    full_return_added = False
    with allure.step("Adding a full return of " + full_return_item + " to the cart"):
        popup, item_grid, rows = h.get_exchange_grid_rows(main_win)
        target_row = find_row(rows, full_return_item)
        if target_row is not None:
            target_row.click_input(coords=(300, 20))
            time.sleep(1)
            # A single click doesn't always confirm/add on a non-last row
            # (confirmed live) - if it's still present, select it (click
            # marks is_selected()) then use the retry-based confirm click.
            popup2, _, rows2 = h.get_exchange_grid_rows(main_win)
            if find_row(rows2, full_return_item) is not None:
                h.select_and_click_latest_row(main_win, max_retries=4)
            time.sleep(1)
        popup3, _, rows3 = h.get_exchange_grid_rows(main_win)
        full_return_added = find_row(rows3, full_return_item) is None

    with allure.step("Closing the Return popup"):
        try:
            return_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
            if return_popup.exists() and return_popup.is_visible():
                close_btn = return_popup.child_window(auto_id="conExchangeClose", control_type="Button")
                close_btn.wait("visible", timeout=5)
                h.press_button_robust(close_btn, desc="Return Close button")
                time.sleep(1.5)
        except Exception as e:
            print("Problem closing the Return popup: " + str(e))

    def edit_cart_qty(row, value, attempts=8):
        """Edit one cart line's Quantity cell and report what happened.

        Returns a dict, not a bare value, so the caller can tell the two
        very different failures apart:
          {"edit_found": False}                 -> the inline editor never
                                                   opened (automation issue)
          {"edit_found": True, "before", "after"} -> the app either kept the
                                                   old value (blocked) or
                                                   took the new one (accepted)
        The inline editor is a separate overlay that appears on double-click
        and is flaky to open, so this KEEPS CLICKING - double-click, then
        single-click + F2, then double-click again - until an Edit control
        shows up over the cell, up to `attempts` rounds. One double-click
        and a fixed wait (the previous behaviour) reported "not blocked" for
        an edit that had never happened."""
        cells = row.children()
        qty_cell = cells[3]
        target_rect = qty_cell.rectangle()
        before = qty_cell.window_text()
        edit = None
        for attempt in range(attempts):
            try:
                if attempt % 3 == 0:
                    qty_cell.double_click_input()
                elif attempt % 3 == 1:
                    qty_cell.click_input()
                    time.sleep(0.3)
                    send_keys("{F2}")
                else:
                    qty_cell.click_input()
                    time.sleep(0.2)
                    qty_cell.double_click_input()
            except Exception:
                pass
            edit = _find_qty_edit_near(main_win, target_rect, retries=3)
            if edit is not None:
                break
        if edit is None:
            print("Cart qty edit: inline editor never opened for " + cells[1].window_text()
                  + " after " + str(attempts) + " attempts")
            return {"edit_found": False, "before": before, "after": None}

        edit.click_input()
        edit.type_keys("^a{DELETE}")
        edit.type_keys(value, pause=0.1)
        time.sleep(0.5)
        send_keys("{ENTER}")
        time.sleep(1.5)
        after = None
        item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        for r in item_grid.children(title="row", control_type="DataItem"):
            if r.children()[1].window_text() == cells[1].window_text():
                after = r.children()[3].window_text()
                break
        print("Cart qty edit: " + cells[1].window_text() + " typed " + str(value)
              + " -> before=" + str(before) + " after=" + str(after))
        return {"edit_found": True, "before": before, "after": after}

    def cart_edit_check(barcode, value, step_title):
        """Run one cart quantity edit and classify it:
             blocked        - editor opened, app kept the old quantity (PASS)
             accepted       - editor opened, app took the invalid value (BUG)
             editor-missing - editor never opened (automation, not the app)
             line-missing   - the line was not in the cart at all"""
        with allure.step(step_title):
            item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
            cart_rows = item_grid.children(title="row", control_type="DataItem")
            row = find_row(cart_rows, barcode)
            if row is None:
                return "line-missing", None
            res = edit_cart_qty(row, value)
            if not res["edit_found"]:
                return "editor-missing", res
            if res["after"] is not None and res["after"] == res["before"]:
                return "blocked", res
            return "accepted", res

    cart_over_return_verdict, cart_over_return_detail = cart_edit_check(
        partial_return_item, cart_over_return_attempt,
        "Cart: re-attempting over-return (" + str(cart_over_return_attempt) + ") on the partial-return line")
    cart_over_return_blocked = cart_over_return_verdict == "blocked"

    cart_zero_verdict, cart_zero_detail = cart_edit_check(
        full_return_item, zero_qty_attempt,
        "Cart: attempting to zero out the full-return line's quantity")
    cart_zero_blocked = cart_zero_verdict == "blocked"

    with allure.step("Completing the return sale"):
        a.do_payment_and_close(main_win, item_search_box=None, skip_item_box=True)

    remaining_qty_correct = False
    full_return_removed = False
    unchanged_ok = True
    with allure.step("Reopening Return on the same invoice to verify remaining quantities"):
        popup, _, rows = open_return_and_search()

        target_row = find_row(rows, partial_return_item)
        if target_row is not None:
            remaining_qty = target_row.children()[3].window_text()
            expected_remaining = str(float(partial_return_purchased_qty) - float(partial_return_qty))
            remaining_qty_correct = abs(float(remaining_qty) - float(expected_remaining)) < 0.01

        full_return_removed = find_row(rows, full_return_item) is None

        for barcode in unchanged_items:
            row = find_row(rows, barcode)
            if row is None:
                unchanged_ok = False

        try:
            return_popup = main_win.child_window(auto_id="conExchange", control_type="Window")
            if return_popup.exists() and return_popup.is_visible():
                close_btn = return_popup.child_window(auto_id="conExchangeClose", control_type="Button")
                close_btn.wait("visible", timeout=5)
                h.press_button_robust(close_btn, desc="Return Close button")
                time.sleep(1.5)
        except Exception as e:
            print("Problem closing the Return popup: " + str(e))

    global last_return_validation_results
    last_return_validation_results = {
        "over_return_blocked": over_return_blocked,
        "partial_return_accepted": partial_return_accepted,
        "partial_return_added": partial_return_added,
        "full_return_added": full_return_added,
        "cart_over_return_blocked": cart_over_return_blocked,
        "cart_over_return_verdict": cart_over_return_verdict,
        "cart_over_return_detail": cart_over_return_detail,
        "cart_zero_blocked": cart_zero_blocked,
        "cart_zero_verdict": cart_zero_verdict,
        "cart_zero_detail": cart_zero_detail,
        "remaining_qty_correct": remaining_qty_correct,
        "full_return_removed": full_return_removed,
        "unchanged_ok": unchanged_ok,
    }
    print("Return quantity validation results: " + str(last_return_validation_results))

    for name, verdict, detail in (("cart over-return", cart_over_return_verdict, cart_over_return_detail),
                                  ("cart zero-qty", cart_zero_verdict, cart_zero_detail)):
        if verdict == "accepted":
            allure.attach("APP BUG: %s edit was ACCEPTED - quantity went %s -> %s"
                          % (name, detail["before"], detail["after"]), name + " verdict",
                          allure.attachment_type.TEXT)
        elif verdict in ("editor-missing", "line-missing"):
            allure.attach("AUTOMATION: %s could not be tested (%s) - not an app verdict"
                          % (name, verdict), name + " verdict", allure.attachment_type.TEXT)

    return (
        over_return_blocked and partial_return_accepted and full_return_added and
        cart_over_return_blocked and cart_zero_blocked and
        remaining_qty_correct and full_return_removed and unchanged_ok
    )
