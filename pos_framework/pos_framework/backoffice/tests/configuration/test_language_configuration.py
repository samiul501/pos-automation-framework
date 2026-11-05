# ============================================================
# LANGUAGE CONFIGURATION - converted from the
# posapp-qa-automation suite.
#
# The save reports "Successfully Edited", not "Created": both
# target languages already have a language-pair record in every
# environment, so there is no new pair to make and this always
# replaces that pair's translation row. That is the product
# behaving correctly - see the page object.
#
# The toast is not taken as proof here. The details view is
# reopened and the saved words read back, because a toast only
# says the request was accepted.
# ============================================================

import allure
import pytest
from playwright.sync_api import expect

from backoffice.pages.configuration.language_configuration_page import (
    LanguageConfigurationPage)
from backoffice.support import requires
from backoffice.utils.business_config.language_config import (
    generate_language_translation_data)

pytestmark = pytest.mark.module


@allure.feature("Configuration")
@allure.story("Language Configuration")
def test_saves_a_language_translation_entry(page, profile):
    """Save a translation and read it back out of the details view."""
    requires(profile, screen="language_configuration",
             data=[("language", "target")])
    allure.dynamic.title("Saves a language translation - " + profile.label)

    data = generate_language_translation_data(profile)
    allure.attach(str(data), name="translation data",
                  attachment_type=allure.attachment_type.TEXT)

    language_page = LanguageConfigurationPage(page, profile)
    language_page.open_list()
    language_page.open_language_setup()
    language_page.select_target_language(data["targetLanguage"])
    language_page.fill_translation(data["sourceValue"], data["targetValue"])
    language_page.save_translation()

    message = language_page.toast()
    allure.attach(message or "(no notification appeared)", name="app response",
                  attachment_type=allure.attachment_type.TEXT)
    assert "successfully" in message.lower(), (
        "the translation was not saved - the app said: %s" % (message or "nothing"))

    language_page.view_details(data["targetLanguage"])
    details = language_page.dialog()
    expect(details.get_by_text(data["sourceValue"], exact=True)).to_be_visible()
    expect(details.get_by_text(data["targetValue"], exact=True)).to_be_visible()
