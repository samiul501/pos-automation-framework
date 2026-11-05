# ============================================================
# EMPLOYEE CREATE - converted from the posapp-qa-automation
# suite.
#
# On StoreB this screen is Ant Design, not react-select: its
# comboboxes DO carry accessible names, so the recipe reaches
# them by role+name rather than by wrapper id - and those names
# include the trailing affordance text the app renders inside the
# label ("* Designation ADD NEW"). Dropping it stops the locator
# matching.
#
# The form itself therefore lives in the profile, like every
# other screen here; what stays in this page object is the flow
# no recipe can express: tick User, fill the password pair, add
# the permission row, and only then save.
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class EmployeeCreatePage(BasePage):
    """Employee create flow: personal info, user account permission row,
    save."""

    SCREEN = "employee_create"
    USER_ACCOUNT_SCREEN = "employee_user_account"

    def open_form(self):
        return self.open_create(self.SCREEN)

    def fill_personal_info(self, data):
        """Fills the Personal Info block from this app's recipe.

        On StoreB these are Ant Design comboboxes whose accessible names
        include the label's trailing affordance text ("* Designation ADD
        NEW"); Supervisor and Line Manager only load their options once you
        type, so the recipe drives them as search selects.
        """
        return self.fill_form(self.SCREEN, data)

    def enable_user_account(self, user_account):
        """Ticks "User", fills the password pair, then the Business Unit /
        Office / Warehouse permission row from its own recipe.

        The row's "Office" is a SECOND, distinct combobox from Personal
        Info's "* Office" - the recipe matches it exactly so it cannot
        re-open the one above. The password comes from
        randoms.strong_password() because a weak one is rejected silently:
        no toast, the button simply does nothing.
        """
        page = self.page
        password = user_account["password"]

        page.get_by_role("checkbox", name="User").check()
        page.get_by_role("textbox", name="* Password").fill(password)
        page.get_by_role("textbox", name="* Confirm Password").fill(password)

        return self.fill_form(self.USER_ACCOUNT_SCREEN, user_account)

    def add_button(self):
        return self.page.get_by_role("button", name="Add", exact=True)

    def click_add(self):
        """Adds the permission row. Without this the account section is
        filled but never attached, and the save succeeds with no user."""
        self.add_button().click()
        self.page.wait_for_timeout(1000)
        return self

    def user_account_row(self, user_account):
        """The permission row showing Business Unit ... Office ... Warehouse.
        Row text runs the cells together with no separator, so the three
        values are matched in order rather than as one string."""
        pattern = re.compile(".*".join(
            re.escape(user_account[key]) for key in ("businessUnit", "office", "warehouse")))
        return self.page.get_by_role("row", name=pattern)

    def save_employee(self):
        return self.save_form(self.SCREEN)

    def success_notification(self):
        return self.page.get_by_text(re.compile("created successfully", re.IGNORECASE)).first
