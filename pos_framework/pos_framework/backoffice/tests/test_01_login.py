# ============================================================
# LOGIN - converted from the posapp-qa-automation suite.
#
# Every other test rides a session saved once at the start of the
# run, so nothing else actually exercises signing in. This one
# does: a fresh context with no cookies, through the Cloudflare
# Turnstile check and out the other side.
#
# Worth keeping separate because a broken login looks like every
# test failing at once, and this names the cause in one line.
# ============================================================

import allure
import pytest

from backoffice.pages.base_page import BasePage
from backoffice.pages.login_page import LoginPage

pytestmark = pytest.mark.smoke


@pytest.fixture
def page(browser, reachable_profile):
    """A clean, signed-OUT page.

    Overrides the shared logged-in `page` fixture for this file only -
    with the saved session in place the login form never renders and
    there would be nothing to test.
    """
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    fresh = context.new_page()
    try:
        yield fresh
    finally:
        context.close()


@allure.feature("Back office harness")
def test_signs_in_through_the_turnstile_check(page, reachable_profile):
    """Sign in from scratch and land on the app shell."""
    profile = reachable_profile
    allure.dynamic.title("Signs in from scratch - " + profile.label)

    login = LoginPage(page, profile)
    login.login()

    allure.attach(page.url, name="url after signing in",
                  attachment_type=allure.attachment_type.TEXT)
    assert not login.is_on_login_screen(), \
        "still on the login screen - sign-in did not go through"
    assert page.locator(BasePage.MENU_ENTRY).count() > 0, \
        "signed in but no navigation menu rendered"
