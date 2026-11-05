# ============================================================
# COMBINED FLOW - mirrors the happy-path step order (Login ->
# Transaction -> ...), but at each step runs its negative cases
# FIRST, then exactly one positive/valid action to advance real
# app state to the next step. Independent of both
# positive_tests/test_pos_full.py and the per-step-only
# negative_tests/test_negative_<step>.py files - this file
# intentionally interleaves negative and positive actions in one
# continuous run. Run with:
#   python -m pytest negative_tests/test_negative_positive_flow.py --alluredir=allure-results
# (run from the pos_framework/pos_framework directory)
# ============================================================

import allure
from allure_commons.types import Severity

import config
import pos_helpers as h
import pos_actions as a
import negative_actions as na
import negative_config as nc


def _login_case(case_id):
    return next(c for c in nc.LOGIN_NEGATIVE_CASES if c["case_id"] == case_id)


# ============ Step 1: Login - 3 important negative cases, then 1 valid login ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_01a_login_rejected_wrong_password():
    case = _login_case("wrong_password")
    allure.dynamic.title("01a. Login rejected - " + case["description"])
    h.launch_app()
    rejected = na.attempt_login(case["user_id"], case["password"])
    assert rejected, "Login unexpectedly SUCCEEDED with: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_01b_login_rejected_wrong_user_id():
    case = _login_case("wrong_user_id")
    allure.dynamic.title("01b. Login rejected - " + case["description"])
    rejected = na.attempt_login(case["user_id"], case["password"])
    assert rejected, "Login unexpectedly SUCCEEDED with: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_01c_login_rejected_both_blank():
    case = _login_case("both_blank")
    allure.dynamic.title("01c. Login rejected - " + case["description"])
    rejected = na.attempt_login(case["user_id"], case["password"])
    assert rejected, "Login unexpectedly SUCCEEDED with: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_01d_login_success():
    allure.dynamic.title("01d. Valid Login (advance to Transaction step)")
    a.do_login()


# ============ Step 2: Transaction - negative case(s), then 1 valid transaction ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02a_invalid_item_barcode_not_added():
    case = nc.TRANSACTION_ITEM_NEGATIVE_CASES[0]
    allure.dynamic.title("02a. Item rejected - " + case["description"])
    rejected = na.attempt_add_invalid_item(case["customer"], case["item_barcode"])
    assert rejected, "Non-existent item barcode was unexpectedly ADDED: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02b_invalid_customer_blocks_sale():
    case = nc.TRANSACTION_CUSTOMER_NEGATIVE_CASES[0]
    allure.dynamic.title("02b. Sale should be blocked - " + case["description"])
    blocked = na.attempt_sell_with_invalid_customer(case["customer"], case["item_barcode"], case["valid_customer"])
    assert blocked, "Sale unexpectedly COMPLETED with an invalid customer: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02c_blank_customer_blocks_sale():
    case = nc.TRANSACTION_BLANK_CUSTOMER_NEGATIVE_CASES[0]
    allure.dynamic.title("02c. Sale should be blocked - " + case["description"])
    blocked = na.attempt_sell_without_customer(case["items"], case["valid_customer"])
    assert blocked, "Sale unexpectedly COMPLETED without a customer: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02d_underpay_then_correct_sale():
    case = nc.TRANSACTION_UNDERPAY_NEGATIVE_CASES[0]
    allure.dynamic.title("02d. Underpay rejected then corrected - " + case["description"])
    ok = na.attempt_underpay_then_correct(case["customer"], case["items"])
    assert ok, "Underpay was not rejected, or the corrected-amount retry did not complete the sale: " + case["description"]


# ---- Discount cases, reordered so the riskiest/known-bug ones run LAST -
# if they destabilize the app, fewer tests after them are affected. ----
@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02e_discount_applied_for_group_customer():
    case = nc.DISCOUNT_VALID_CASE
    allure.dynamic.title("02e. Discount applied correctly - " + case["description"])
    ok = na.verify_discount_applied_for_group_customer(
        case["customer"], case["items"],
        case["expected_total_bill"], case["expected_total_discount"], case["expected_grand_total"]
    )
    assert ok, "Discount did not apply correctly for the group customer: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02f_discount_not_applied_other_customer():
    case = nc.TRANSACTION_DISCOUNT_NEGATIVE_CASES[0]
    allure.dynamic.title("02f. Discount should not apply - " + case["description"])
    ok = na.verify_discount_not_applied(case["customer"], case["item_barcode"], case["expected_full_price"])
    assert ok, "Customer-group discount leaked to a customer outside the group: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02g_discount_hidden_without_customer():
    case = nc.DISCOUNT_BLANK_CUSTOMER_CASE
    allure.dynamic.title("02g. Discount hidden without a customer - " + case["description"])
    ok = na.verify_discount_hidden_without_customer(
        case["item_barcode"], case["expected_full_price"], case["cleanup_customer"]
    )
    assert ok, "Discount was shown even though no customer was entered: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02h_discount_scales_with_quantity():
    case = nc.DISCOUNT_QUANTITY_SCALING_CASE
    allure.dynamic.title("02h. Discount scales with quantity - " + case["description"])
    ok = na.verify_discount_scales_with_quantity(
        case["customer"], case["item_barcode"], case["quantity"],
        case["expected_total_bill"], case["expected_total_discount"], case["expected_grand_total"]
    )
    assert ok, "Discount did not scale correctly with quantity: " + case["description"]


# ---- Known-bug / lower-priority edge cases - run last on purpose ----
@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.NORMAL)
def test_02i_discount_updates_on_customer_switch():
    case = nc.DISCOUNT_CUSTOMER_SWITCH_CASE
    allure.dynamic.title("02i. Discount should recalculate on customer switch - " + case["description"])
    ok = na.verify_discount_updates_on_customer_switch(
        case["item_barcode"], case["initial_customer"], case["switch_to_customer"],
        case["expected_discounted_total"], case["expected_total_discount"]
    )
    assert ok, "Discount did not recalculate after switching to the discounted-group customer mid-cart: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.NORMAL)
def test_02j_discount_stacks_with_manual_offer():
    case = nc.DISCOUNT_MANUAL_OFFER_COMBO_CASE
    allure.dynamic.title("02j. Discount stacks with manual offer - " + case["description"])
    ok = na.verify_discount_stacks_with_manual_offer(
        case["customer"], case["item_barcode"], case["offer_discount_type"], case["offer_discount_value"],
        case["expected_total_discount"], case["expected_other_discount"], case["expected_grand_total"]
    )
    assert ok, "Group discount and manual Cost Guard offer did not stack as expected: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_02k_valid_transaction():
    allure.dynamic.title("02k. Valid Transaction (advance to next step)")
    main_win = h.get_main_window()
    txn = next(t for t in config.TRANSACTIONS if t["customer"] == "01700000006")
    item_search_box = a.add_customer_and_items(main_win, txn["customer"], txn["items"])
    a.do_payment_and_close(main_win, item_search_box)


# ============ Step 3: Hold & Recall - negative cases ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.CRITICAL)
def test_03a_recall_with_no_holds():
    allure.dynamic.title("03a. Recall with zero pending holds should be a safe no-op")
    ok = na.verify_recall_with_no_holds()
    assert ok, "Recalling with zero pending holds did not behave as a safe no-op"


@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.CRITICAL)
def test_03b_hold_empty_cart_no_phantom():
    allure.dynamic.title("03b. Holding an empty cart (F9) should show 'No item selected', not 'Hold Successfully'")
    ok = na.attempt_hold_empty_cart()
    assert ok, (
        "Hold (F9) on an empty cart did not show the 'No item selected' popup "
        "(it shows 'Hold Successfully (0)' instead - the on-screen Hold button gets it right), "
        "or a phantom/garbage invoice got queued"
    )


@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.CRITICAL)
def test_03c_discount_survives_hold_recall():
    case = nc.DISCOUNT_HOLD_RECALL_CASE
    allure.dynamic.title("03c. Discount should survive Hold -> Recall - " + case["description"])
    ok = na.verify_discount_survives_hold_recall(
        case["customer"], case["item_barcode"], case["expected_grand_total"], case["expected_total_discount_after_recall"]
    )
    assert ok, "Discount did not survive the Hold -> Recall cycle correctly: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.NORMAL)
def test_03d_discount_after_hold_recall_customer_switch():
    case = nc.DISCOUNT_HOLD_RECALL_SWITCH_CASE
    allure.dynamic.title("03d. Discount should reapply after switching back - " + case["description"])
    ok = na.verify_discount_after_hold_recall_customer_switch(
        case["group_customer"], case["other_customer"], case["item_barcode"],
        case["expected_grand_total_discounted"], case["expected_total_discount_discounted"],
        case["expected_grand_total_full_price"]
    )
    assert ok, "Discount did not reapply after switching back to the group customer post-recall: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.CRITICAL)
def test_03e_no_double_recall():
    case = nc.DOUBLE_RECALL_CASE
    allure.dynamic.title("03e. No double recall - " + case["description"])
    ok = na.verify_no_double_recall(case["customer"], case["item_barcode"])
    assert ok, "An already-completed invoice was recallable a second time: " + case["description"]


@allure.feature("POS Negative+Positive Flow")
@allure.story("Hold and Recall")
@allure.severity(Severity.CRITICAL)
def test_03f_recall_specific_non_latest_invoice():
    case = nc.RECALL_SPECIFIC_INVOICE_CASE
    allure.dynamic.title("03f. Recall a specific non-latest invoice - " + case["description"])
    ok = na.verify_recall_specific_invoice(
        case["before_customer"], case["before_item"],
        case["target_customer"], case["target_item"],
        case["target_offer_discount_type"], case["target_offer_discount_value"],
        case["after_customer"], case["after_item"]
    )
    assert ok, "Recalling a specific non-latest invoice did not restore the correct customer/item: " + case["description"]


# ============ Step 4: Return ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Return Quantity Validation")
@allure.severity(Severity.CRITICAL)
def test_04a_return_quantity_validation():
    case = nc.RETURN_QUANTITY_VALIDATION_CASE
    allure.dynamic.title("04a. Return quantity validation - " + case["description"])
    ok = na.verify_return_quantity_validation(
        case["customer"], case["items"],
        case["partial_return_item"], case["partial_return_purchased_qty"],
        case["over_return_attempt"], case["partial_return_qty"],
        case["cart_over_return_attempt"],
        case["full_return_item"], case["zero_qty_attempt"],
        case["unchanged_items"]
    )
    r = na.last_return_validation_results
    verdicts = ("cart over-return: %s | cart zero-qty: %s"
                % (r.get("cart_over_return_verdict"), r.get("cart_zero_verdict")))
    failed = [k for k, v in r.items() if k.endswith(("_blocked", "_accepted", "_added", "_correct", "_removed", "_ok")) and v is False]
    assert ok, ("Return validation failed on %s. %s. (accepted = APP BUG, editor-missing = automation could not open the cell editor)"
                % (failed, verdicts))


# ============ Step 5: Logout ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Logout")
@allure.severity(Severity.NORMAL)
def test_05_logout():
    """Logout is its own step so Allure shows it separately from the
    app close - a logout that silently fails used to be invisible inside
    the teardown."""
    allure.dynamic.title("05. Logout after Return")
    main_win = h.get_main_window()
    a.do_logout(main_win)
    with allure.step("Verifying the login screen is back"):
        login_field = main_win.child_window(auto_id="userName", control_type="Edit")
        back_at_login = h.wait_until_ready(login_field, timeout=15, poll_interval=0.5,
                                           desc="User ID field (post-logout)")
        assert back_at_login, "Logout did not return to the login screen (User ID field not visible)"


# ============ Teardown ============
@allure.feature("POS Negative+Positive Flow")
@allure.story("Close Application")
@allure.severity(Severity.NORMAL)
def test_99_close_app():
    allure.dynamic.title("99. Close App")
    main_win = h.get_main_window()
    a.close_app(main_win)
