# ============================================================
# TEST CASES - only test flows live here. Business logic lives in
# pos_actions.py, test data in config.py. Add new test cases here.
# ============================================================

import json
import pytest
from allure_commons.types import Severity
import allure

import config
import pos_helpers as h
import pos_actions as a

# Carries invoice numbers produced during the run forward to the Exchange/Return
# steps that need them, so they always operate on a fresh invoice instead of a
# hardcoded one that eventually goes stale.
_state = {"web_verify": []}


# ============ Step 1: Login ============
@allure.feature("POS Full Flow")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_01_login():
    allure.dynamic.title("01. Launch App and Login")
    h.launch_app()
    a.do_login()


# ============ Step 2: 6 Transactions ============
@allure.feature("POS Full Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
@pytest.mark.parametrize("txn_number,txn", list(enumerate(config.TRANSACTIONS, start=1)))
def test_02_transaction(txn_number, txn):
    offer_tag = " (with Offer)" if txn["offer"] else ""
    step_num = str(txn_number + 1).zfill(2)
    allure.dynamic.title(
        step_num + ". Transaction " + str(txn_number) + offer_tag +
        " - Customer " + txn['customer'] + ", " + str(len(txn['items'])) + " item(s)"
    )

    main_win = h.get_main_window()
    item_search_box = a.add_customer_and_items(main_win, txn["customer"], txn["items"])

    # Read the discount values now (if this txn expects one) but assert on
    # them only after payment completes below - that way a mismatch still
    # fails this test and shows up in the report, but never leaves the cart
    # unpaid, so a failure here can't corrupt state for the next test.
    discount_check = None
    if "expected_discounted_total" in txn:
        with allure.step("Reading the applied customer-group discount for verification"):
            grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
            total_discount = main_win.child_window(auto_id="TextBoxTotalDiscount", control_type="Text").window_text()
            discount_check = (grand_total, total_discount)

    # Read the GrandTotal that will actually be charged (post-offer, if any)
    # so it can be handed off to the web report verification pass later -
    # this is read regardless of whether the txn has an explicit discount
    # expectation, since every transaction's invoice can be checked against
    # the web report's Net Payable.
    if txn["offer"]:
        a.do_offer_flow(main_win, txn["offer"]["discount_type"], txn["offer"]["discount_value"])

    with allure.step("Reading the final GrandTotal for web report verification"):
        web_verify_grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()

    a.do_payment_and_close(main_win, item_search_box)

    if discount_check is not None:
        grand_total, total_discount = discount_check
        assert grand_total == txn["expected_discounted_total"], (
            "Expected discounted GrandTotal " + txn["expected_discounted_total"] +
            " but got " + grand_total + " - the customer-group discount setup may have changed"
        )
        assert total_discount == txn["expected_total_discount"], (
            "Expected TotalDiscount " + txn["expected_total_discount"] +
            " but got " + total_discount + " - the customer-group discount setup may have changed"
        )

    with allure.step("Capturing this transaction's invoice number for web report verification"):
        invoice_no = h.get_most_recent_invoice_no(main_win)
        _state["web_verify"].append({
            "invoice_no": invoice_no,
            "customer": txn["customer"],
            "expected_grand_total": web_verify_grand_total,
            "label": "Transaction " + str(txn_number),
        })


# ============ Step 3: 7th Transaction - Hold + Recall ============
@allure.feature("POS Full Flow")
@allure.story("Hold and Recall Transaction")
@allure.severity(Severity.CRITICAL)
def test_03_hold_recall_transaction():
    allure.dynamic.title(
        "08. Transaction 7 (Hold & Recall) - Customer " + config.HOLD_RECALL_TRANSACTION['customer'] +
        ", " + str(len(config.HOLD_RECALL_TRANSACTION['items'])) + " item(s)"
    )

    main_win = h.get_main_window()
    item_search_box = a.add_customer_and_items(
        main_win,
        config.HOLD_RECALL_TRANSACTION["customer"],
        config.HOLD_RECALL_TRANSACTION["items"]
    )

    a.do_hold_and_recall(main_win, item_search_box)

    item_search_group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    item_search_box = item_search_group.child_window(auto_id="TextBox", control_type="Edit")

    with allure.step("Reading the final GrandTotal for web report verification"):
        web_verify_grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()

    a.do_payment_and_close(main_win, item_search_box)

    _state["exchange_invoice_no"] = h.get_latest_invoice_no(main_win)
    _state["web_verify"].append({
        "invoice_no": h.get_most_recent_invoice_no(main_win),
        "customer": config.HOLD_RECALL_TRANSACTION["customer"],
        "expected_grand_total": web_verify_grand_total,
        "label": "Hold & Recall Transaction",
    })


# ============ Step 4: Exchange Transaction ============
@allure.feature("POS Full Flow")
@allure.story("Exchange Transaction")
@allure.severity(Severity.CRITICAL)
def test_04_exchange_transaction():
    invoice_no = _state["exchange_invoice_no"]
    allure.dynamic.title("09. Exchange Transaction - Invoice " + invoice_no)

    main_win = h.get_main_window()
    item_search_box = a.do_exchange(
        main_win,
        invoice_no,
        config.EXCHANGE_TRANSACTION["new_item_barcodes"]
    )

    # Read the final GrandTotal for web report verification - confirmed
    # live that an Exchange invoice mixes a negative row (the exchanged-out
    # item) with positive rows (the new item(s)), netting to this total;
    # the web report shows the same mix and nets to the same Net Payable,
    # so no special-casing is needed here beyond capturing the number.
    with allure.step("Reading the final GrandTotal for web report verification"):
        web_verify_grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()

    a.do_payment_and_close(main_win, item_search_box)

    with allure.step("Capturing this transaction's invoice number for web report verification"):
        _state["web_verify"].append({
            "invoice_no": h.get_most_recent_invoice_no(main_win),
            "customer": config.HOLD_RECALL_TRANSACTION["customer"],
            "expected_grand_total": web_verify_grand_total,
            "label": "Exchange Transaction",
        })


# ============ Step 5: Return Transaction ============
@allure.feature("POS Full Flow")
@allure.story("Return Transaction")
@allure.severity(Severity.CRITICAL)
def test_05_return_transaction():
    main_win = h.get_main_window()
    invoice_no = h.get_latest_invoice_no(main_win)
    allure.dynamic.title("10. Return Transaction - Invoice " + invoice_no)

    a.do_return(main_win, invoice_no)

    # Read the final GrandTotal (negative, confirmed live - e.g. -781 for a
    # single returned item) for web report verification before payment.
    with allure.step("Reading the final GrandTotal for web report verification"):
        web_verify_grand_total = main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text()

    # No new item was added for Return, so payment proceeds directly
    # from the cash amount field without an item_search_box
    a.do_payment_and_close(main_win, item_search_box=None, skip_item_box=True)

    with allure.step("Capturing this transaction's invoice number for web report verification"):
        _state["web_verify"].append({
            "invoice_no": h.get_most_recent_invoice_no(main_win),
            "customer": config.HOLD_RECALL_TRANSACTION["customer"],
            "expected_grand_total": web_verify_grand_total,
            "label": "Return Transaction",
        })


# ============ Step 6: Logout ============
@allure.feature("POS Full Flow")
@allure.story("Logout")
@allure.severity(Severity.NORMAL)
def test_06_logout():
    allure.dynamic.title("11. Logout after all transactions")
    main_win = h.get_main_window()
    a.do_logout(main_win)


# ============ Step 7: App Close ============
@allure.feature("POS Full Flow")
@allure.story("Close Application")
@allure.severity(Severity.NORMAL)
def test_07_close_app():
    allure.dynamic.title("12. Close application after logout")

    with allure.step("Saving captured invoice numbers for the web report verification pass"):
        with open(config.WEB_VERIFY_DATA_FILE, "w") as f:
            json.dump(_state["web_verify"], f, indent=2)

    main_win = h.get_main_window()
    a.close_app(main_win)
