# ============================================================
# SMOKE - proves the harness itself works against whichever app
# was selected, before any business test is worth running.
#
#   APP=demostore pytest backoffice -c backoffice/pytest.ini -m smoke
#   APP=storeb         pytest backoffice -c backoffice/pytest.ini -m smoke
#
# If these fail, nothing else in the suite means anything: either
# the environment is unreachable, the credentials are wrong, or
# the menu trails in the profile have drifted from the app.
# ============================================================

import allure
import pytest

from backoffice.pages.base_page import BasePage
from backoffice.pages.login_page import LoginPage


pytestmark = pytest.mark.smoke


def _attach(name, body):
    text = body if isinstance(body, str) else "\n".join(str(x) for x in body)
    print("\n--- %s ---\n%s" % (name, text))
    allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)


@allure.feature("Back office harness")
def test_profile_is_complete(profile):
    """The selected profile declares everything a run needs."""
    allure.dynamic.title("Profile is usable - " + profile.describe())
    _attach("profile", [
        "key      : " + str(profile.key),
        "base url : " + str(profile.base_url),
        "database : " + str(profile.database),
        "user     : " + (profile.username() or "(missing)"),
        "screens  : " + ", ".join(sorted(profile.nav)),
        "flags    : " + str(profile.flags),
    ])
    assert profile.base_url, "profile has no base_url"
    assert profile.username(), "no username - set %s in .env" % profile.username_env
    assert profile.password(), "no password - set %s in .env" % profile.password_env
    assert profile.nav, "profile declares no menu trails"


@allure.feature("Back office harness")
def test_can_sign_in(page, profile):
    """The shared session actually signed in: the app shell is there and
    the login form is not."""
    allure.dynamic.title("Signs in to " + profile.label)
    BasePage(page, profile).goto_app()
    login = LoginPage(page, profile)
    _attach("url after opening the app", page.url)
    assert not login.is_on_login_screen(), \
        "still on the login screen - the saved session did not work (try --fresh-login)"
    assert page.locator(BasePage.MENU_ENTRY).count() > 0, "no navigation menu rendered"


@allure.feature("Back office harness")
def test_menu_trails_resolve(page, profile):
    """Every menu trail the profile declares can actually be walked.

    This is the check that catches an app redesign early: the tests below
    all navigate by menu, so one renamed entry breaks them all, and the
    failure would otherwise surface as an unrelated 'field not found'.
    """
    allure.dynamic.title("Menu trails still match " + profile.label)
    BasePage(page, profile).goto_app()
    page.wait_for_selector(BasePage.MENU_ENTRY, timeout=45000)
    page.wait_for_timeout(2000)

    top_level = set()
    for trail in profile.nav.values():
        if trail:
            top_level.add(trail[0])

    rendered = [t.strip() for t in page.eval_on_selector_all(
        BasePage.MENU_ENTRY, "els => els.map(e => (e.innerText || '').trim())") if t.strip()]
    _attach("menu entries rendered", rendered)
    _attach("top level the profile expects", sorted(top_level))

    missing = sorted(m for m in top_level if not any(m in r for r in rendered))
    assert not missing, (
        "these top-level menus are in the profile but not in the app: %s\n"
        "rendered: %s" % (", ".join(missing), rendered))
