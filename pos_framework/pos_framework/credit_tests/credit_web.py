# ============================================================
# CREDIT WEB - the backend half of the credit flow: create a
# customer that has a credit limit and credit days.
#
# THE ONE THING THAT MATTERS HERE (confirmed live 2026-09-22)
# ------------------------------------------------------------
# Opening /config/custoemerProfile/create straight by URL renders
# a STRIPPED form: no Partner Billing Name, no Credit Limit, no
# Credit Days, no Is Monthly, no Territory, no Customer Point.
# The app gates those fields on permissions that are only loaded
# while walking the menu, so the create page MUST be reached as a
# person reaches it:
#
#     sidebar "Configuration" -> "Customer Profile" -> "Customer"
#
# Both routes end on the same URL, which is why this was so
# confusing to diagnose - the URL is not the difference, the
# navigation is. open_create_customer() therefore never calls
# page.goto() for the create page.
#
# The sidebar itself swallows ordinary clicks (a sibling <ul>
# intercepts pointer events - the same problem web_helpers hit),
# so every sidebar click here is force=True.
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

from credit_tests import credit_config as ccfg


_OPTION_SELECTOR = "[class*='-option'], div[role='option']"


# ---- session --------------------------------------------------------

def login(playwright, headless=True):
    """Fresh browser logged into the backend. Returns (browser, page).

    Fixed 1920x1080 viewport under headless for the same reason the other
    suites use one: no_viewport collapses the sidebar there and the
    navigation this module depends on stops working."""
    browser = playwright.chromium.launch(headless=headless, args=["--start-maximized"])
    if headless:
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
    else:
        context = browser.new_context(no_viewport=True)
    page = context.new_page()
    _goto(page, config.WEB_BASE_URL)
    page.wait_for_selector("input[name='mobileNo']", timeout=30000)
    page.fill("input[name='mobileNo']", config.WEB_MOBILE)
    page.fill("input[name='password']", config.WEB_PASSWORD)
    page.click("button:has-text('LOG IN')")
    _settle(page, 5)
    return browser, page


def _settle(page, seconds=0):
    """Wait for quiet, but never fail because the page never goes idle -
    this app keeps a notification socket open, so networkidle can simply
    never fire on a page that is fully rendered."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    if seconds:
        time.sleep(seconds)


def _goto(page, url, seconds=2):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        page.goto(url, timeout=45000)
    _settle(page, seconds)


# ---- navigation: menu only, never by URL ----------------------------

def open_create_customer(page):
    """Configuration -> Customer Profile -> Customer (create).

    Asserts the credit fields actually rendered, because the stripped
    form looks perfectly normal otherwise and would fail much later with
    a confusing "field not found"."""
    page.locator(".menuContent", has_text=ccfg.MENU_CONFIGURATION).first.click(force=True)
    time.sleep(2)
    page.locator("a[href='" + ccfg.ROUTE_CUSTOMER_PROFILE + "']").first.click(force=True)
    _settle(page, 4)
    page.locator("button", has_text=ccfg.CREATE_BUTTON_TEXT).first.click(force=True)
    _settle(page, 5)

    if page.locator("input[name='" + ccfg.INPUT_CREDIT_LIMIT + "']").count() == 0:
        raise AssertionError(
            "the create-customer form rendered WITHOUT the credit fields - it was probably "
            "reached by URL instead of through Configuration -> Customer Profile -> Customer"
        )
    return page


# ---- react-select ---------------------------------------------------

def _visible_options(page):
    return [t.strip() for t in page.eval_on_selector_all(
        _OPTION_SELECTOR, "els => els.map(e => (e.innerText || '').trim())") if t.strip()]


def pick(page, container_id, option_text, attempts=3):
    """Open a react-select by container id and click one option. The
    transparent overlay means force=True on both the control and the
    option; the retry covers options that arrive a beat late."""
    page.wait_for_selector("#" + container_id, timeout=15000)
    for attempt in range(1, attempts + 1):
        page.click("#" + container_id, force=True)
        time.sleep(1.0 + 0.5 * attempt)
        options = _visible_options(page)
        if option_text in options or page.locator(_OPTION_SELECTOR, has_text=option_text).count():
            page.locator(_OPTION_SELECTOR, has_text=option_text).first.click(force=True)
            time.sleep(0.8)
            return True
        if attempt == attempts:
            raise AssertionError(
                "no option %r in #%s after %d attempts; options seen: %r"
                % (option_text, container_id, attempts, options))
        page.keyboard.press("Escape")
        time.sleep(0.6)
    return False


def _fill(page, name, value):
    field = page.locator("input[name='" + name + "']").first
    field.click()
    field.fill(str(value))
    time.sleep(0.3)


# ---- create ---------------------------------------------------------

def create_credit_customer(page, spec):
    """Fill and save the create-customer form from `spec` (see
    credit_data.new_customer_spec). Only the fields that are actually
    required are touched - Office, Partner Name, Billing Name, Mobile No,
    Territory, Customer Point - plus the two this suite exists for:
    Credit Limit and Credit Days.

    Returns the toast/confirmation text the app showed."""
    pick(page, ccfg.SELECT_OFFICE, spec["office"])
    time.sleep(1.5)

    _fill(page, ccfg.INPUT_PARTNER_NAME, spec["name"])
    if page.locator("input[name='" + ccfg.INPUT_BILLING_NAME + "']").count():
        _fill(page, ccfg.INPUT_BILLING_NAME, spec["name"])
    _fill(page, ccfg.INPUT_MOBILE, spec["mobile"])

    _fill(page, ccfg.INPUT_CREDIT_DAYS, spec["credit_days"])
    _fill(page, ccfg.INPUT_CREDIT_LIMIT, spec["credit_limit"])

    pick(page, ccfg.SELECT_TERRITORY, spec["territory"])
    pick(page, ccfg.SELECT_CUSTOMER_POINT, spec["customer_point"])

    page.locator("button:has-text('SAVE')").first.click(force=True)
    return wait_for_toast(page)


def form_values(page):
    """What the form currently holds - attached to the report so a failed
    save shows exactly what was typed."""
    out = {}
    for name in (ccfg.INPUT_PARTNER_NAME, ccfg.INPUT_BILLING_NAME, ccfg.INPUT_MOBILE,
                 ccfg.INPUT_CREDIT_LIMIT, ccfg.INPUT_CREDIT_DAYS):
        loc = page.locator("input[name='" + name + "']").first
        out[name] = loc.input_value() if loc.count() else "(absent)"
    for cid in (ccfg.SELECT_OFFICE, ccfg.SELECT_TERRITORY, ccfg.SELECT_CUSTOMER_POINT):
        loc = page.locator("#" + cid).first
        out[cid] = loc.inner_text().strip() if loc.count() else "(absent)"
    return out


def wait_for_toast(page, timeout=20):
    """Poll for the save confirmation instead of reading once.

    The toast is transient - a single read after a fixed sleep caught an
    empty string on a save that had in fact succeeded (confirmed live: the
    customer was in the database while the test reported no toast). Polling
    catches it whether it appears in 1s or 8s, and returns whatever was
    there when it faded."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        text = toast_text(page)
        if text:
            return text
        last = text
        time.sleep(0.5)
    _settle(page, 1)
    return toast_text(page) or last


def toast_text(page):
    """Whatever notification the app raised, joined into one string."""
    texts = []
    for sel in (".Toastify__toast-body", "[class*='toast']", "[role='alert']"):
        for t in page.eval_on_selector_all(sel, "els => els.map(e => (e.innerText||'').trim())"):
            if t and t not in texts:
                texts.append(t)
    return " | ".join(texts)


def screenshot(page, path, full_page=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    page.screenshot(path=path, full_page=full_page)
    return path
