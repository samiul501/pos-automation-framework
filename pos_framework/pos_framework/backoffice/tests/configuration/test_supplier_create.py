# ============================================================
# SUPPLIER CREATE - converted from the posapp-qa-automation
# suite. The list search here needs "View" pressed before it
# filters, which is why finding the record again goes through
# the page object rather than typing in the box.
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.configuration.supplier_create_page import SupplierCreatePage
from backoffice.support import requires
from backoffice.utils.entity_master_data.supplier_config import generate_supplier_data

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Supplier Profile")
def test_creates_a_new_supplier(page, profile):
    """Create a supplier through the menu and find it again in the list."""
    requires(profile, screen="supplier_create", button=True, form=True,
             data=[("office",)])
    allure.dynamic.title("Creates a supplier - " + profile.label)

    data = generate_supplier_data(profile)
    allure.attach(str(data), name="supplier data",
                  attachment_type=allure.attachment_type.TEXT)

    supplier_page = SupplierCreatePage(page, profile)
    supplier_page.open_form()
    supplier_page.fill_partner_details(data)
    supplier_page.add_supplier_address(data["shippingAddress"])
    supplier_page.save_supplier()

    message = supplier_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = supplier_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)

    assert "created successfully" in message.lower(), (
        "supplier %r was not created - the app said: %s"
        % (data["partnerName"], message or " | ".join(complaints) or "nothing"))

    supplier_page.search(data["partnerName"])
    expect(supplier_page.supplier_row(data["partnerName"])).to_be_visible()
