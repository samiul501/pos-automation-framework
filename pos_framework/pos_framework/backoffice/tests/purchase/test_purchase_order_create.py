# ============================================================
# LOCAL PURCHASE ORDER - converted from the
# posapp-qa-automation suite.
#
# This one selects master data rather than creating it: the
# supplier and the item must already exist in the environment,
# which is why the profile supplies both the string to type into
# each picker and the option text that should come back. If
# those records are ever removed the test skips or fails on the
# picker, and the message says which record is missing.
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.purchase.purchase_order_page import PurchaseOrderPage
from backoffice.support import requires
from backoffice.utils.po_config import get_local_purchase_order_data

pytestmark = pytest.mark.module


@allure.feature("Purchase")
@allure.story("Purchase Order")
def test_creates_a_local_purchase_order(page, profile):
    """Raise a local PO for one line of an existing item."""
    requires(profile, screen="purchase_order", button=True, form=True,
             data=[("office",), ("supplier",), ("item_lookup",)])
    allure.dynamic.title("Creates a local purchase order - " + profile.label)

    data = get_local_purchase_order_data(profile)
    allure.attach(str(data), name="purchase order data",
                  attachment_type=allure.attachment_type.TEXT)

    po_page = PurchaseOrderPage(page, profile)
    po_page.open_form()
    po_page.fill_order_details(data)
    po_page.add_line_item()

    # The line has to be on the order before saving means anything.
    expect(po_page.line_item_row(data["itemCode"])).to_be_visible()

    po_page.save_order()

    message = po_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = po_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)

    assert "created successfully" in message.lower(), (
        "the purchase order was not created - the app said: %s"
        % (message or " | ".join(complaints) or "nothing"))
