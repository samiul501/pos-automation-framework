# ============================================================
# ITEM CREATE - converted from the posapp-qa-automation
# suite, which ran it against StoreB only. Nothing here names an
# app: the menu trail, the create-button label and the UOM all
# come from the profile, so the same test is the DemoStore
# test and the StoreB test.
# ============================================================

import allure
import pytest

from backoffice.pages.configuration.item_create_page import ItemCreatePage
from backoffice.support import requires
from backoffice.utils.entity_master_data.item_config import generate_item_data

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Item Profile")
def test_creates_a_new_item(page, profile):
    """Create an item through the menu and confirm the app says so."""
    requires(profile, screen="item_create", button=True, form=True)
    allure.dynamic.title("Creates an item - " + profile.label)

    data = generate_item_data(profile)
    allure.attach(str(data), name="item data",
                  attachment_type=allure.attachment_type.TEXT)

    item_page = ItemCreatePage(page, profile)
    item_page.open_form()
    item_page.fill_basic_info(data)
    item_page.save_item()

    message = item_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    complaints = item_page.validation_errors()
    if complaints:
        allure.attach("\n".join(complaints), name="form validation",
                      attachment_type=allure.attachment_type.TEXT)
        message = message or " | ".join(complaints)

    # Read the toast rather than waiting on the element: it is transient,
    # and a save that HAD succeeded has come back as an empty locator more
    # than once elsewhere in this repo. The text is also worth reporting -
    # "Auto itemcode is active for this account" is a very different
    # failure from a validation error, and the message says which.
    assert "created successfully" in message.lower(), \
        "item %r was not created - the app said: %s" % (
            data["masterItemName"], message or "nothing")
