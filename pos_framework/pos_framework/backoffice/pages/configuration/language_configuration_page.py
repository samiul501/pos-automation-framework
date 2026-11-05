# ============================================================
# LANGUAGE CONFIGURATION - converted from the
# posapp-qa-automation suite.
#
# This screen is a modal, not a page, and it is the one place in
# the suite where a successful save reports "Successfully Edited"
# rather than "Successfully Created" - see select_target_language
# for why that is correct behaviour and not a defect.
# ============================================================

import re

from backoffice.pages.base_page import BasePage


class LanguageConfigurationPage(BasePage):
    """Language Setup modal: target language, translation row, save, and
    the read-only details view used to confirm a save persisted."""

    SCREEN = "language_configuration"

    def open_list(self):
        """Just the menu trail - the create button lives on the list header
        and is pressed separately by open_language_setup()."""
        self.open(self.SCREEN)
        try:
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        return self

    def open_language_setup(self):
        """The list header action button's accessible name is "+ Language
        Setup"; an exact match will not match because of the "+" icon."""
        self.page.get_by_role("button", name="Language Setup").last.click(force=True)
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def dialog(self):
        return self.page.get_by_role("dialog")

    def select_target_language(self, name):
        """Only two target languages (Bangla, Arabic) exist system-wide and
        both already have a language-pair record in every environment - so
        this always EDITS that pair's translation row rather than creating a
        new pair. The app says "Successfully Edited" accordingly; that is
        expected, and success_notification() accepts either word.

        "Language To" is an antd Select whose rendered placeholder text sits
        behind its own input for click purposes, and the list page's filter
        row reuses the same id pattern OUTSIDE the modal - so the input is
        targeted by id scoped to the dialog, never by visible text.
        """
        self.dialog().locator("#translateLanguage").click()
        self.page.get_by_role("option", name=name, exact=True).click()
        self.page.wait_for_timeout(500)
        return self

    def fill_translation(self, source_value, target_value):
        """Fills the single translation row the modal renders by default."""
        dialog = self.dialog()
        dialog.locator("#rows_0_baseLanguageValue").fill(source_value)
        dialog.locator("#rows_0_translateLanguageValue").fill(target_value)
        return self

    def save_translation(self):
        self.dialog().get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def success_notification(self):
        return self.page.get_by_text(
            re.compile("successfully (created|edited)", re.IGNORECASE)).first

    def language_row(self, target_language_name):
        """Row for e.g. "English en Bangla bn" - row text has no separator
        between cells, so the cells are matched in order."""
        pattern = re.compile(
            r"English\s+en\s+%s" % re.escape(target_language_name), re.IGNORECASE)
        return self.page.get_by_role("row", name=pattern).first

    def view_details(self, target_language_name):
        """Opens the read-only "Language Details" view via its eye icon, to
        confirm a saved translation entry actually persisted - the toast
        alone only says the request was accepted."""
        self.language_row(target_language_name).get_by_role("button", name="eye").click()
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self
