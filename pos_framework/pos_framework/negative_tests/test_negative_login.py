# ============================================================
# NEGATIVE TEST CASES - Login step only. Completely independent of
# test_pos_full.py - run with:
#   python -m pytest negative_tests/test_negative_login.py --alluredir=allure-results
# (run from the pos_framework/pos_framework directory, same as the happy path)
# ============================================================

import pytest
import allure
from allure_commons.types import Severity

import pos_helpers as h
import pos_actions as a
import negative_actions as na
import negative_config as nc


@allure.feature("POS Negative Cases")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
def test_00_launch_app():
    allure.dynamic.title("00. Launch App (setup for negative login cases)")
    h.launch_app()


@allure.feature("POS Negative Cases")
@allure.story("Login")
@allure.severity(Severity.CRITICAL)
@pytest.mark.parametrize(
    "case", nc.LOGIN_NEGATIVE_CASES, ids=[c["case_id"] for c in nc.LOGIN_NEGATIVE_CASES]
)
def test_login_rejected(case):
    allure.dynamic.title("Login should be rejected - " + case["description"])
    rejected = na.attempt_login(case["user_id"], case["password"])
    assert rejected, "Login unexpectedly SUCCEEDED with: " + case["description"]


@allure.feature("POS Negative Cases")
@allure.story("Login")
@allure.severity(Severity.NORMAL)
def test_99_close_app():
    allure.dynamic.title("99. Close App (teardown after negative login cases)")
    main_win = h.get_main_window()
    # Reuses the happy-path close flow as-is (X button + confirm popup) -
    # just called here, pos_actions.py itself is never modified.
    a.close_app(main_win)
