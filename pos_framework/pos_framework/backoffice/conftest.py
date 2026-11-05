# ============================================================
# BACK OFFICE FIXTURES - scoped to this folder only.
#
# pytest applies a conftest.py to the directory it sits in and
# below, so everything here (Playwright, login, the app profile)
# reaches the back-office tests and NOTHING ELSE. The exe suites
# one level up keep running exactly as they did - that separation
# is the whole reason this file is not at the repo root.
#
# WHAT A TEST GETS
#   profile   the environment under test (APP=demostore | storeb)
#   page      a browser page already logged into that environment
#
# LOGGING IN ONCE
# ---------------
# Signing in for every test is the single biggest waste in a web
# suite. The session logs in once per profile, saves the cookies
# to auth/<app>-user.json, and every test opens a context from
# that file. Delete the file (or pass --fresh-login) to force a
# new sign-in when a session goes stale.
# ============================================================

import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backoffice.profiles import registry

BACKOFFICE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_DIR = os.path.dirname(BACKOFFICE_DIR)
AUTH_DIR = os.path.join(BACKOFFICE_DIR, "auth")


def _load_env():
    """Read the framework's .env so credentials never sit in code.
    Real environment variables win, so CI can override without
    touching the file."""
    env_file = os.path.join(FRAMEWORK_DIR, ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env()


def pytest_addoption(parser):
    parser.addoption("--app", action="store", default=None,
                     help="environment to test: " + ", ".join(registry.names()))
    parser.addoption("--fresh-login", action="store_true", default=False,
                     help="ignore the saved session and sign in again")


def pytest_configure(config):
    """Make the run answer to the chosen app in the two places it
    otherwise would not.

    RESULTS GO TO THEIR OWN FOLDER. pytest.ini names one --alluredir, so
    running DemoStore and then StoreB would pile both into it and a
    failure would not say which environment it came from. The app's key
    is appended here instead, giving one report per environment.

    THE DATABASE FOLLOWS THE APP. db_helpers reads $DB_NAME (default
    DemoStore). A back-office test that verifies against the database
    must read the database BEHIND THE APP IT JUST DROVE - StoreB is the SME
    database - so the profile sets it rather than the person remembering
    to. Only this pytest process is affected; the exe suites are not.
    """
    profile = registry.get(config.getoption("--app"))

    results_dir = getattr(config.option, "allure_report_dir", None)
    if results_dir and not results_dir.rstrip("/\\").endswith(profile.key):
        config.option.allure_report_dir = results_dir.rstrip("/\\") + "-" + profile.key

    if profile.database:
        os.environ["DB_NAME"] = profile.database


def pytest_report_header(config):
    profile = registry.get(config.getoption("--app"))
    return ("back office: " + profile.describe()
            + "\ndatabase   : " + str(profile.database)
            + "\nresults    : " + str(getattr(config.option, "allure_report_dir", None)))


def _host_reachable(url, timeout=6):
    """Can this machine even resolve and reach the host?

    Some environments are only visible over the office VPN - devmgm does
    not resolve from outside it. Discovering that as a DNS stack trace in
    the middle of a browser step tells the reader nothing, so it is
    checked up front and reported as a skip with the reason.
    """
    import socket
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    if not host:
        return False, "no host in base_url %r" % url
    try:
        socket.getaddrinfo(host, 443)
    except Exception as e:
        return False, "%s does not resolve from this machine (%s) - VPN?" % (host, type(e).__name__)
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True, ""
    except Exception as e:
        return False, "%s resolves but port 443 is unreachable (%s)" % (host, type(e).__name__)


@pytest.fixture(scope="session")
def profile(pytestconfig):
    """The environment under test. Every page object reads its menu
    trails, button labels and master data from this."""
    chosen = registry.get(pytestconfig.getoption("--app"))
    if not chosen.username() or not chosen.password():
        pytest.skip("no credentials for %s - set %s / %s in .env"
                    % (chosen.key, chosen.username_env, chosen.password_env))
    return chosen


@pytest.fixture(scope="session")
def reachable_profile(profile):
    """The profile, once the environment has been shown to be reachable.
    Anything that opens a browser depends on this rather than on
    `profile`, so an unreachable environment skips cleanly."""
    ok, reason = _host_reachable(profile.base_url)
    if not ok:
        pytest.skip("%s is not reachable: %s" % (profile.label or profile.key, reason))
    return profile


@pytest.fixture(scope="session")
def base_url(profile):
    """Overrides pytest-playwright's own base_url fixture, so
    page.goto('/') lands on the right app."""
    return profile.base_url


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, pytestconfig):
    """Watching a run should fill the screen.

    With --headed the browser is started maximised; headless runs are
    untouched, since a window size means nothing there.
    """
    if not pytestconfig.getoption("--headed"):
        return browser_type_launch_args
    args = list(browser_type_launch_args.get("args", []))
    if "--start-maximized" not in args:
        args.append("--start-maximized")
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(scope="session")
def window_args(pytestconfig):
    """How every context in this suite sizes its window.

    Headless: a fixed 1920x1080. Confirmed the hard way elsewhere in
    this repo that a small or absent viewport collapses the navigation,
    and every menu-driven step then fails for a reason that looks
    nothing like the real cause.

    Headed: no viewport at all, so the page fills the maximised window
    instead of sitting in a 1920x1080 box inside it.
    """
    if pytestconfig.getoption("--headed"):
        return {"no_viewport": True}
    return {"viewport": {"width": 1920, "height": 1080}}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, window_args):
    return {**browser_context_args, **window_args}


@pytest.fixture(scope="session")
def auth_state(browser, reachable_profile, pytestconfig, window_args):
    """Sign in once per profile; hand every test the saved session."""
    profile = reachable_profile
    os.makedirs(AUTH_DIR, exist_ok=True)
    state_file = os.path.join(AUTH_DIR, profile.key + "-user.json")

    if pytestconfig.getoption("--fresh-login") and os.path.exists(state_file):
        os.remove(state_file)

    if os.path.exists(state_file):
        return state_file

    from backoffice.pages.login_page import LoginPage

    context = browser.new_context(**window_args)
    page = context.new_page()
    try:
        LoginPage(page, profile).login()
        context.storage_state(path=state_file)
    finally:
        context.close()
    return state_file


@pytest.fixture
def page(browser, auth_state, profile, window_args):
    """A logged-in page. Named `page` deliberately: it replaces
    pytest-playwright's anonymous one, so a test that forgets to log in
    cannot accidentally run signed out."""
    context = browser.new_context(
        storage_state=auth_state,
        base_url=profile.base_url,
        **window_args
    )
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()
