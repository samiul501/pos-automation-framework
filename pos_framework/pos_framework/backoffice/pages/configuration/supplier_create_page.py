# ============================================================
# SUPPLIER CREATE - converted from the posapp-qa-automation
# suite. Navigation now comes from the profile; the two things
# this screen taught the source suite are kept:
#
#   1. the form re-renders after its master data loads and can
#      silently throw away a selection (BasePage.select_sticky_option)
#   2. the Supplier list's search box does NOT filter live - it
#      only applies when "View" is pressed
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class SupplierCreatePage(BasePage):
    """Supplier Profile create flow: partner details, supplier address,
    save, and list search."""

    SCREEN = "supplier_create"

    def open_form(self):
        self.open_create(self.SCREEN)
        # The form re-renders shortly after paint once its initial data
        # (the Attachment widget, dropdown master data) finishes loading,
        # which detaches an already-open react-select mid-interaction.
        # Waiting for network idle here avoids racing that re-render.
        try:
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        return self

    def fill_partner_details(self, data):
        """Fills whatever this app's Supplier form is made of. Its selects
        go through the sticky kind because of the re-render described
        above."""
        return self.fill_form(self.SCREEN, data)

    def add_supplier_address(self, address):
        """The Supplier Details address must be added to the list via "Add
        List" before Save, otherwise submission is rejected - the same
        pattern as Customer create's Shipping Details."""
        if not self.profile.flag("address_list_required"):
            # This app saves a partner without one; pressing "Add List"
            # here would be inventing a step the product does not have.
            return self
        self.page.get_by_role("textbox", name="Address", exact=True).fill(address)
        self.page.get_by_role("button", name="Add List").click(force=True)
        self.page.wait_for_timeout(1000)
        return self

    def save_supplier(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first

    def search(self, partner_name):
        """Unlike the Customer list, the Supplier list's search box does not
        filter live - it only applies once "View" is clicked."""
        self.page.get_by_placeholder("Search...").fill(partner_name)
        self.page.get_by_role("button", name="View", exact=True).click(force=True)
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def supplier_row(self, partner_name):
        return self.page.get_by_role("cell", name=partner_name, exact=True).first
