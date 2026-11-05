# ============================================================
# CUSTOMER CREATE - converted from the posapp-qa-automation
# suite, with one check added that the source could not have had:
# that the permission-gated fields are actually on the form.
#
# On DemoStore this form renders WITHOUT Credit Limit and
# Credit Days unless it was reached through the menu. A suite
# that fills the stripped version passes while testing a form
# the user never sees, so the test asserts the fields are there
# before it trusts anything else it did.
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.configuration.customer_create_page import CustomerCreatePage
from backoffice.support import requires
from backoffice.utils.entity_master_data.customer_config import generate_customer_data

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Customer Profile")
def test_creates_a_new_customer(page, profile):
    """Create a customer through the menu and find it again in the list."""
    requires(profile, screen="customer_create", button=True, form=True,
             data=[("office",), ("customer", "territory")])
    allure.dynamic.title("Creates a customer - " + profile.label)

    data = generate_customer_data(profile)
    allure.attach(str(data), name="customer data",
                  attachment_type=allure.attachment_type.TEXT)

    customer_page = CustomerCreatePage(page, profile)
    customer_page.open_form()

    if profile.flag("menu_only_form_gating"):
        assert customer_page.has_credit_fields(), (
            "Credit Limit / Credit Days are missing - this is the stripped "
            "form the app renders when it is not reached through the menu, "
            "so nothing filled here would be the real thing")

    customer_page.fill_partner_details(data)
    customer_page.add_shipping_address(data["shippingAddress"])
    customer_page.save_customer()

    message = customer_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = customer_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)

    assert "created successfully" in message.lower(), (
        "customer %r was not created - the app said: %s"
        % (data["partnerName"], message or " | ".join(complaints) or "nothing"))

    # The toast only says the request was accepted. The list is where the
    # record either exists or does not.
    customer_page.search_box().fill(data["partnerName"])
    expect(customer_page.customer_row(data["partnerName"])).to_be_visible()
