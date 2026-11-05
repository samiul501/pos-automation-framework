# ============================================================
# OTHER PARTNER (Supplier & Customer) CREATE - converted from
# the posapp-qa-automation suite. The list opens on the
# "SUPPLIER & CUSTOMER [BOTH]" tab, so this creates a partner
# that is both at once.
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.configuration.other_partner_create_page import OtherPartnerCreatePage
from backoffice.support import requires
from backoffice.utils.entity_master_data.other_partner_config import (
    generate_other_partner_data)

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Other Partner Profile")
def test_creates_a_new_other_partner(page, profile):
    """Create a supplier-and-customer partner and find it in the list."""
    requires(profile, screen="other_partner_create", button=True, form=True,
             data=[("office",), ("customer", "territory")])
    allure.dynamic.title("Creates a supplier & customer partner - " + profile.label)

    data = generate_other_partner_data(profile)
    allure.attach(str(data), name="partner data",
                  attachment_type=allure.attachment_type.TEXT)

    partner_page = OtherPartnerCreatePage(page, profile)
    partner_page.open_form()
    partner_page.fill_partner_details(data)
    partner_page.add_shipping_address(data["shippingAddress"])
    partner_page.save_partner()

    message = partner_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = partner_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)

    assert "created successfully" in message.lower(), (
        "partner %r was not created - the app said: %s"
        % (data["partnerName"], message or " | ".join(complaints) or "nothing"))

    partner_page.search_box().fill(data["partnerName"])
    expect(partner_page.partner_row(data["partnerName"])).to_be_visible()
