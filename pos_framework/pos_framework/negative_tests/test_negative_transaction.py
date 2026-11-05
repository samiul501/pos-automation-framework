# ============================================================
# NEGATIVE TEST CASES - Transaction step only. Completely independent
# of test_pos_full.py - run with:
#   python -m pytest negative_tests/test_negative_transaction.py --alluredir=allure-results
# (run from the pos_framework/pos_framework directory, same as the happy path)
# ============================================================

import allure
from allure_commons.types import Severity

import pos_helpers as h
import pos_actions as a
import negative_actions as na
import negative_config as nc


@allure.feature("POS Negative Cases")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_00_launch_and_login():
    allure.dynamic.title("00. Launch App and Login (setup for negative transaction cases)")
    h.launch_app()
    a.do_login()


@allure.feature("POS Negative Cases")
@allure.story("Transaction")
@allure.severity(Severity.CRITICAL)
def test_invalid_item_barcode_not_added():
    case = nc.TRANSACTION_ITEM_NEGATIVE_CASES[0]
    allure.dynamic.title("Item should not be added - " + case["description"])
    rejected = na.attempt_add_invalid_item(case["customer"], case["item_barcode"])
    assert rejected, "Non-existent item barcode was unexpectedly ADDED to the cart: " + case["description"]


@allure.feature("POS Negative Cases")
@allure.story("Transaction")
@allure.severity(Severity.NORMAL)
def test_99_close_app():
    allure.dynamic.title("99. Close App (teardown after negative transaction cases)")
    main_win = h.get_main_window()
    a.close_app(main_win)
