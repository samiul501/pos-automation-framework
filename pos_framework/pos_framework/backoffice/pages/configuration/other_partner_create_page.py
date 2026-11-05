# ============================================================
# OTHER PARTNER (Supplier & Customer) CREATE - converted from the
# posapp-qa-automation suite.
#
# The list opens on the "SUPPLIER & CUSTOMER [BOTH]" tab by
# default, so the create button reached here is the both-roles
# one. Like Supplier create, this form re-renders in the
# background and can discard a selection, so its dropdowns go
# through select_sticky_option.
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class OtherPartnerCreatePage(BasePage):
    """Other Partner Profile create flow: partner details, shipping
    address, save, and list search."""

    SCREEN = "other_partner_create"

    def open_form(self):
        self.open_create(self.SCREEN)
        try:
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        return self

    def fill_partner_details(self, data):
        """Fills whatever this app's Other Partner form is made of."""
        return self.fill_form(self.SCREEN, data)

    def add_shipping_address(self, address):
        """Same "Add List" rule as Customer and Supplier create."""
        if not self.profile.flag("address_list_required"):
            # This app saves a partner without one; pressing "Add List"
            # here would be inventing a step the product does not have.
            return self
        self.page.get_by_role("textbox", name="Address", exact=True).fill(address)
        self.page.get_by_role("button", name="Add List").click(force=True)
        self.page.wait_for_timeout(1000)
        return self

    def save_partner(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first

    def search_box(self):
        return self.page.get_by_placeholder("Search...")

    def partner_row(self, partner_name):
        """Partner Name and Partner Billing Name share the same generated
        value, so both columns can match - .first picks either."""
        return self.page.get_by_role("cell", name=partner_name, exact=True).first
