# ============================================================
# EMPLOYEE CREATE (with a user account) - converted from the
# posapp-qa-automation suite.
#
# Two things this test is careful about, both learned there:
#   * the permission row must be ADDED, not merely filled - the
#     save succeeds either way, but without "Add" the employee
#     has no user account and the test would have proved nothing
#   * creating an employee and a user in one submit is slow, so
#     the notification gets a longer wait than elsewhere
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.configuration.employee_create_page import EmployeeCreatePage
from backoffice.support import requires
from backoffice.utils.entity_master_data.emp_config import (
    generate_employee_data, generate_user_account_data)

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Employee")
def test_creates_a_new_employee_with_a_user_account(page, profile):
    """Create an employee together with the user account that signs in."""
    requires(profile, screen="employee_create", button=True, form=True,
             data=[("office",),
                   ("employee", "supervisor"), ("employee", "lineManager"),
                   ("employee", "businessUnit"), ("employee", "warehouse")])
    allure.dynamic.title("Creates an employee with a user account - " + profile.label)

    data = generate_employee_data(profile)
    user_account = generate_user_account_data(profile)
    allure.attach(str(data), name="employee data",
                  attachment_type=allure.attachment_type.TEXT)

    employee_page = EmployeeCreatePage(page, profile)
    employee_page.open_form()
    employee_page.fill_personal_info(data)
    employee_page.enable_user_account(user_account)
    employee_page.click_add()

    # Proof the permission row was attached, before anything is saved.
    expect(employee_page.user_account_row(user_account)).to_be_visible()

    employee_page.save_employee()

    message = employee_page.toast(timeout_seconds=30)
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = employee_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)

    assert "created successfully" in message.lower(), (
        "employee %r was not created - the app said: %s"
        % (data["name"], message or " | ".join(complaints) or "nothing"))
