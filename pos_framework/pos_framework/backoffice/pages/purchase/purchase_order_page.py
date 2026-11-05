# ============================================================
# PURCHASE ORDER (Local PO) - converted from the
# posapp-qa-automation suite.
#
# This screen is a react-select/Formik form with NO aria-label
# wiring, unlike the Ant Design forms (Employee, Item). Its
# dropdowns therefore cannot be found by accessible name at all;
# they are scoped either through their underlying
# <input name="..."> or through their visible placeholder text.
# That is a property of the screen, not a style choice here.
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class PurchaseOrderPage(BasePage):
    """Local Purchase Order create flow: navigation, react-select
    dropdowns, line items, save."""

    SCREEN = "purchase_order"

    def open_form(self):
        return self.open_create(self.SCREEN)

    def fill_order_details(self, order_details):
        """Office, Supplier, Item, Qty and Rate, as this app arranges them.

        The Supplier and Item pickers only fetch after three letters are
        typed, which is why the recipe gives each a separate search string
        - and why those strings are profile data: they name records that
        must already exist in that environment.
        """
        return self.fill_form(self.SCREEN, order_details)

    def add_line_item(self):
        """Without this the header is filled but the order has no lines,
        and Save is rejected."""
        self.page.get_by_role("button", name="Add", exact=True).click(force=True)
        self.page.wait_for_timeout(1000)
        return self

    def line_item_row(self, item_name_or_pattern):
        return self.page.get_by_role("row", name=item_name_or_pattern)

    def save_order(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first
