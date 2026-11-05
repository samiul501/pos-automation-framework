# ============================================================
# ITEM CREATE - converted from the posapp-qa-automation suite.
#
# This is the screen where the two apps diverge most, and it is
# worth being explicit about why this page object looks thin.
#
#   StoreB          Configuration -> Entity Master Data -> Item Profile
#                an Ant Design form: Master Item code, Master Item
#                name, UOM. Save.
#
#   DemoStore  Configuration -> Item Profile
#                a react-select/Formik form that also demands
#                Supplier, Barcode, a Category -> Sub -> Minor
#                chain, both Tax Setups and a Sales Price, and
#                that REFUSES a manual item code because the
#                account generates them (read off the live app).
#
# Those are not the same form. Rather than branch per app here,
# each profile describes its own form (Profile.forms) and
# BasePage.fill_form walks that description - so this page object
# holds the flow, and the apps hold their own shapes.
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class ItemCreatePage(BasePage):
    """Item Profile create flow: open, fill, save."""

    SCREEN = "item_create"

    def open_form(self):
        """Walks this environment's menu trail, then presses its create
        button ("Add Item" in both apps today)."""
        return self.open_create(self.SCREEN)

    def fill_basic_info(self, data):
        return self.fill_form(self.SCREEN, data)

    def save_item(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first
