# ============================================================
# CUSTOMER CREATE - converted from the posapp-qa-automation
# suite. The menu walk moved into the profile; every selector and
# every hard-won note below is the original suite's.
#
# One rule added from this repo's own experience with DemoStore:
# this form MUST be reached through the menu. Opened by URL it
# renders without Credit Limit, Credit Days, Territory and
# Customer Point - the test then fills a form that was never the
# real one and passes having proved nothing. BasePage.open()
# enforces that; this page object never calls goto().
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class CustomerCreatePage(BasePage):
    """Customer Profile create flow: partner details, shipping address,
    save, and list search."""

    SCREEN = "customer_create"

    def open_form(self):
        """Menu trail from the profile, then this app's create button.

        The label differs: StoreB's is "Add Customer", DemoStore's is just
        "Customer". Either way the accessible name carries a "+" icon, so
        press_create matches loosely rather than exactly.
        """
        return self.open_create(self.SCREEN)

    def fill_partner_details(self, data):
        """Fills whatever this app's Customer form is made of.

        Office and Territory are react-select widgets whose input has no
        accessible name - their id is duplicated across every select on the
        page, which breaks label association - so the recipe targets them by
        the wrapper's own stable id.
        """
        return self.fill_form(self.SCREEN, data)

    def has_credit_fields(self):
        """Whether the permission-gated credit fields made it onto the form.

        Note the field names: the app calls Credit Days "paymentDays" in
        the DOM. Waiting rather than asking once, because this part of the
        form paints last.
        """
        return (self.wait_for_field("creditLimit")
                and self.wait_for_field("paymentDays"))

    def add_shipping_address(self, address):
        """The Shipping Details address must be added to the list via "Add
        List" before Save, otherwise submission is rejected with "Please Add
        Shipping Address!" - the address being typed in the box is not
        enough."""
        if not self.profile.flag("address_list_required"):
            # This app saves a partner without one; pressing "Add List"
            # here would be inventing a step the product does not have.
            return self
        self.page.get_by_role("textbox", name="Address", exact=True).fill(address)
        self.page.get_by_role("button", name="Add List").click(force=True)
        self.page.wait_for_timeout(1000)
        return self

    def save_customer(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first

    def search_box(self):
        return self.page.get_by_placeholder("Search...")

    def customer_row(self, partner_name):
        """Partner Name and Partner Billing Name share the same generated
        value, so both columns match this cell text - .first picks either."""
        return self.page.get_by_role("cell", name=partner_name, exact=True).first
