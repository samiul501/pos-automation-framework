"""The jobs that have to be done over and over before any testing starts.

    python setup_tasks.py register   - token, registration, login, open session
    python setup_tasks.py reset      - reset the installed app and stop
    python setup_tasks.py full       - reset, then everything above

Run from the dashboard, where each one is a button at the top of the page.
Every step narrates itself, so it is obvious what is happening and where it
stopped if it stops.

Registration ticks the first four on the left and all five in the middle,
leaves the right-hand column alone, and sets Item Code Length to 4.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import win32clipboard
from playwright.sync_api import sync_playwright
from pywinauto.keyboard import send_keys

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK = os.path.dirname(HERE)
sys.path.insert(0, FRAMEWORK)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_env():
    path = os.path.join(FRAMEWORK, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


os.environ.setdefault("DB_NAME", "DemoStore")
_load_env()

import db_helpers as db          # noqa: E402
import pos_helpers as H          # noqa: E402

# ---------------------------------------------------------------- settings

# The two back offices a counter can be registered from. Only DemoStore's
# database is reachable from here, so the two cross-checks (the token really
# is the counter's, the session really reached the server) are done for that
# one and skipped for StoreC - the browser and exe steps are identical.
ENVIRONMENTS = {
    "demostore": {
        "label": "devdemostore",
        "url": "https://demo-backoffice.example.com/",
        "user_env": "WEB_MOBILE",
        "pass_env": "WEB_PASSWORD",
        "counter": "sami2",
        "counter_id": 20183,
        "database": "DemoStore",      # None means no cross-checks
        "headless": True,
    },
    "storec": {
        "label": "StoreC",
        "url": "https://storec-backoffice.example.com/",
        "user_env": "STOREC_MOBILE",
        "pass_env": "STOREC_PASSWORD",
        "counter": "sami2",
        "counter_id": None,             # looked up only when a database is set
        "database": None,
        # Cloudflare's bot check never clears for a headless browser here,
        # so this one runs with the window on screen.
        "headless": False,
    },
}

ENV = ENVIRONMENTS["demostore"]       # replaced by --env at startup
COUNTER_NAME = ENV["counter"]
COUNTER_ID = ENV["counter_id"]

EMPLOYEE = os.getenv("POS_USER_ID", "")
PASSWORD = os.getenv("POS_PASSWORD", "")
OPENING_CASH = 0

PKG_NAME = "CF9BD7D4-0F9A-4730-8950-05D032861D46"
PKG_FAMILY = PKG_NAME + "_6g9azff0e1qkt"
LOCALSTATE = os.path.join(os.environ["LOCALAPPDATA"], "Packages",
                          PKG_FAMILY, "LocalState")

# Registration screen - left column, first four
LEFT_4 = ["IsAllowSalesPerson", "IsSync", "IsPrint", "isDeclarationSlipPrint"]
# Middle column, all five
MIDDLE_5 = ["IsDirectPoint", "IsItemSearch", "ViewItemDetail",
            "ViewCostPrice", "ViewItemCode"]
# The right-hand column is left exactly as it comes.
ITEM_CODE_LENGTH = "4"

TOTAL_STEPS = {"register": 5, "reset": 1, "full": 6}
_step = {"n": 0, "of": 0}


def log(*bits):
    print(*bits, flush=True)


def step(title):
    _step["n"] += 1
    log("")
    log("[%d/%d] %s" % (_step["n"], _step["of"], title))
    log("-" * 66)


def note(text):
    log("        " + text)


# --------------------------------------------------------------- reset

def reset_app():
    step("Resetting the installed application")
    full = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-AppxPackage -Name '%s').PackageFullName" % PKG_NAME],
        capture_output=True, text=True, timeout=120).stdout.strip()
    if not full:
        raise SystemExit("POSAPP does not appear to be installed")
    note("package: %s" % full)
    note("closing the app if it is running ...")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process -Name '*POSAPP*' -ErrorAction SilentlyContinue "
         "| Stop-Process -Force; Start-Sleep 3; Reset-AppxPackage -Package '%s'" % full],
        capture_output=True, text=True, timeout=300)
    time.sleep(6)
    left = os.listdir(LOCALSTATE) if os.path.isdir(LOCALSTATE) else []
    if left:
        note("WARNING - the reset left files behind: %s" % left)
    else:
        note("done, local data is empty")


# --------------------------------------------- token, from the back office

def generate_token():
    step("Collecting a fresh token from %s" % ENV["label"])
    user = os.getenv(ENV["user_env"], "")
    pwd = os.getenv(ENV["pass_env"], "")
    if not user or not pwd:
        raise SystemExit("%s / %s are missing from .env"
                         % (ENV["user_env"], ENV["pass_env"]))

    headless = ENV.get("headless", True)
    if not headless:
        note("this environment has a bot check - the browser will be visible")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless,
                                    args=[] if headless else ["--start-maximized"])
        ctx = (browser.new_context(viewport={"width": 1800, "height": 1100})
               if headless else browser.new_context(no_viewport=True))
        page = ctx.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)

        note("opening %s ..." % ENV["url"])
        page.goto(ENV["url"], wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(6000)

        if page.locator("#loginMobileNo").count():
            note("signing in as %s ..." % user)
            page.locator("#loginMobileNo").fill(user)
            page.locator("#loginPassword, input[type='password']").first.fill(pwd)
            page.wait_for_timeout(4000)        # let any bot check settle
            btn = page.get_by_role("button", name="LOG IN", exact=False).first
            if btn.count():
                btn.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(18000)
        if not page.locator(".menuContent").count():
            raise SystemExit("could not sign in to %s - the page never showed its menu"
                             % ENV["url"])
        note("signed in")

        def menu(label, wait):
            entry = page.locator(".menuContent", has_text=label).first
            if not entry.count():
                entry = page.get_by_text(label, exact=True).first
            entry.click(force=True)
            page.wait_for_timeout(wait)

        note("POS > Setup > Counter Setup ...")
        menu("POS", 2500)
        menu("Setup", 4000)
        menu("Counter Setup", 11000)

        note("searching for the %s counter ..." % COUNTER_NAME)
        box = page.get_by_placeholder("Search", exact=False)
        if box.count():
            box.first.click(force=True)
            box.first.fill(COUNTER_NAME)
            page.keyboard.press("Enter")

        # The grid can hold fifty-odd counters and the search is a round trip,
        # so wait for the row rather than guessing how long it takes - eight
        # seconds was not enough on StoreC and the counter looked missing.
        row = page.locator("table tbody tr", has_text=COUNTER_NAME).first
        try:
            row.wait_for(state="visible", timeout=45000)
        except Exception:
            raise SystemExit("counter %s is not on the list at %s"
                             % (COUNTER_NAME, ENV["label"]))

        note("opening Generate Token ...")
        # The action is plain text inside its own cell, not a <button>, and the
        # grid re-renders right after the search - a click that lands mid-render
        # is swallowed and no dialog ever opens. So confirm the dialog arrived
        # and press again if it did not.
        dialog = page.locator("[role='dialog']")
        opened = False
        for attempt in (1, 2, 3):
            page.wait_for_timeout(1500)
            row.locator("td", has_text="Generate Token").last.click(force=True)
            try:
                dialog.first.wait_for(state="visible", timeout=15000)
                opened = True
                break
            except Exception:
                note("the dialog did not open (attempt %d) - trying again" % attempt)
        if not opened:
            raise SystemExit("the Generate Token dialog never opened for %s"
                             % COUNTER_NAME)

        note("pressing Generate New ...")
        gen = page.get_by_role("button", name="Generate New", exact=False).first
        gen.wait_for(state="visible", timeout=30000)
        gen.click(force=True)
        page.wait_for_timeout(10000)

        text = page.locator(
            "[role='dialog'] p, [class*='MuiDialogContent'] p").first.inner_text()
        token = text.split(":", 1)[1].strip() if ":" in text else text.strip()
        browser.close()

    note("token received: %d characters" % len(token))
    if ENV["database"] and COUNTER_ID:
        row = db._query("SELECT Token, LastTokenGeneratedDate FROM pos.POSCounter "
                        "WHERE CounterId = ?", [COUNTER_ID])[0]
        if not token.startswith(str(row["Token"])[:60]):
            raise SystemExit("the token on screen does not match the counter's stored token")
        note("matches the counter record (generated %s)"
             % str(row["LastTokenGeneratedDate"])[:19])
    else:
        note("no database configured for %s - skipping the record check"
             % ENV["label"])

    json.dump({"environment": ENV["label"], "counter": COUNTER_NAME, "token": token},
              open(os.path.join(HERE, "token.json"), "w"), indent=2)
    return token


# ------------------------------------------------------------- the exe

def to_clipboard(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def click_first(win, titles, timeout=2):
    """Popups here only answer to their own button - Enter does nothing."""
    for t in titles:
        b = win.child_window(title=t, control_type="Button")
        if b.exists(timeout=timeout) and b.is_visible():
            b.click_input()
            time.sleep(2)
            return t
    return None


def _to_registration(win):
    """Get to the Registration screen from wherever the app happens to be.

    Without a reset the app usually opens already registered and logged in -
    there is no Registration button on the POS screen, so log out first.
    """
    if win.child_window(auto_id="txtToken", control_type="Edit").exists(timeout=3):
        return win

    reg = win.child_window(auto_id="btnRegistration", control_type="Button")
    if reg.exists(timeout=4):
        note("at the login screen")
        reg.click_input()
        time.sleep(6)
        return win

    note("the app is already signed in - logging out first")
    click_first(win, ("OK", "Ok", "No", "Cancel"))
    out = win.child_window(auto_id="btnLogOut", control_type="Button")
    if out.exists(timeout=5):
        out.click_input()
        time.sleep(4)
        b = win.child_window(title="Logout", control_type="Button")
        if b.exists(timeout=6):
            b.click_input()
            time.sleep(12)

    reg = win.child_window(auto_id="btnRegistration", control_type="Button")
    if not reg.exists(timeout=20):
        raise SystemExit("could not reach the Registration screen - "
                         "run Reset + Register + Session instead")
    reg.click_input()
    time.sleep(6)
    return win


def register(token):
    step("Registering the exe against %s" % COUNTER_NAME)
    note("launching the app ...")
    H.launch_app()
    win = H.get_main_window()
    time.sleep(3)

    win = _to_registration(win)

    box = win.child_window(auto_id="txtToken", control_type="Edit")
    box.wait("visible", timeout=60)
    box.click_input()
    time.sleep(1)
    # 2000+ characters, and the control exposes no ValuePattern - paste it
    to_clipboard(token)
    send_keys("^a")
    send_keys("^v")
    time.sleep(3)
    note("token pasted")

    for auto_id in LEFT_4 + MIDDLE_5:
        cb = win.child_window(auto_id=auto_id, control_type="CheckBox")
        cb.wait("visible", timeout=15)
        if cb.get_toggle_state() != 1:
            cb.click_input()
            time.sleep(0.4)
    note("left column, first four : %s" % ", ".join(LEFT_4))
    note("middle column, all five : %s" % ", ".join(MIDDLE_5))
    note("right column            : left untouched")

    length = win.child_window(auto_id="txtItemCodeLength", control_type="Edit")
    length.set_focus()
    length.set_edit_text(ITEM_CODE_LENGTH)
    time.sleep(1)
    note("item code length        : %s" % ITEM_CODE_LENGTH)

    win.child_window(title="Save", control_type="Button").click_input()
    time.sleep(6)
    click_first(win, ("OK", "Ok"), timeout=10)      # "Successfully Created"
    note("saved")

    go = win.child_window(title="Go To Login", control_type="Button")
    if go.exists(timeout=5):
        go.click_input()
        time.sleep(8)
    return win


def login(win):
    step("Logging in as %s" % (EMPLOYEE or "(no POS_USER_ID in .env)"))
    if not EMPLOYEE or not PASSWORD:
        raise SystemExit("POS_USER_ID / POS_PASSWORD are missing from .env")
    u = win.child_window(auto_id="userName", control_type="Edit")
    u.wait("visible", timeout=60)
    u.click_input()
    send_keys("^a")
    u.type_keys(EMPLOYEE, with_spaces=True)
    p = win.child_window(auto_id="UserPassword", control_type="Edit")
    p.click_input()
    send_keys("^a")
    p.type_keys(PASSWORD, with_spaces=True)
    time.sleep(1)
    win.child_window(auto_id="btnLogin", control_type="Button").click_input()
    time.sleep(15)
    click_first(win, ("OK", "Ok", "No", "Cancel"))
    note(win.child_window(auto_id="AppTitleBarText").window_text())


def counter_selected(win):
    lbl = win.child_window(auto_id="cmbo_market_ID", control_type="Text")
    return lbl.exists(timeout=1) and COUNTER_NAME in (lbl.window_text() or "")


def wait_processing(win, limit=900):
    end = time.time() + limit
    shown = False
    while time.time() < end:
        s = win.child_window(auto_id="StatusText", control_type="Text")
        if not s.exists(timeout=1):
            return True
        if not shown:
            note("the app is downloading its data, this takes a few minutes ...")
            shown = True
        time.sleep(10)
    return False


def open_session(win):
    step("Opening a session on %s" % COUNTER_NAME)
    before = _open_session_ids()

    win.child_window(auto_id="Shell_Outlet", control_type="ListItem").click_input()
    time.sleep(6)
    cmb = win.child_window(auto_id="cmbCusto", control_type="ComboBox")
    cmb.wait("visible", timeout=30)
    for _ in range(3):
        if counter_selected(win):
            break
        cmb.click_input()
        time.sleep(3)
        item = win.child_window(title=COUNTER_NAME, control_type="ListItem")
        if item.exists(timeout=5):
            item.click_input()
            time.sleep(3)
    if not counter_selected(win):
        raise SystemExit("could not select the %s counter" % COUNTER_NAME)
    note("counter selected")

    win.child_window(title="Open Session", control_type="Button").click_input()
    time.sleep(4)

    start = win.child_window(auto_id="PrimaryButton", control_type="Button")
    start.wait("visible", timeout=30)
    if OPENING_CASH:
        cash = win.child_window(auto_id="InputBox", control_type="Edit")
        cash.click_input()
        send_keys("^a")
        cash.type_keys(str(OPENING_CASH), pause=0.1)
        time.sleep(1)
    note("opening cash: %s" % OPENING_CASH)
    start.click_input()
    time.sleep(10)

    wait_processing(win)
    time.sleep(5)
    click_first(win, ("OK", "Ok", "No", "Cancel"))
    win.set_focus()
    send_keys("{ENTER}")
    time.sleep(3)
    click_first(win, ("OK", "Ok", "No", "Cancel"))

    if before is None:
        note("session opened (no database for %s, so not checked against the server)"
             % ENV["label"])
        return None

    for _ in range(12):
        fresh = [i for i in _open_session_ids() if i not in before]
        if fresh:
            note("session #%s is open on the server" % max(fresh))
            return max(fresh)
        time.sleep(5)
    note("WARNING - the app looks ready but no new session reached the server")
    return None


def _open_session_ids():
    """None when this environment has no database we can read."""
    if not (ENV["database"] and COUNTER_ID):
        return None
    return [r["CounterSessionId"] for r in db._query(
        """SELECT TOP 20 CounterSessionId FROM pos.CounterSession
            WHERE CounterId = ? ORDER BY CounterSessionId DESC""", [COUNTER_ID])]


# ------------------------------------------------------------------ driver

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task", choices=["register", "reset", "full"])
    ap.add_argument("--env", default=os.getenv("SETUP_ENV", "demostore"),
                    choices=sorted(ENVIRONMENTS),
                    help="which back office to take the token from")
    args = ap.parse_args()

    global ENV, COUNTER_NAME, COUNTER_ID
    ENV = ENVIRONMENTS[args.env]
    COUNTER_NAME = ENV["counter"]
    COUNTER_ID = ENV["counter_id"]
    if ENV["database"]:
        os.environ["DB_NAME"] = ENV["database"]

    _step["of"] = TOTAL_STEPS[args.task]
    started = time.time()
    log("=" * 66)
    log("  exe setup - %s" % args.task)
    log("  environment %s  (%s)" % (ENV["label"], ENV["url"]))
    log("  counter %s, employee %s" % (COUNTER_NAME, EMPLOYEE))
    log("=" * 66)

    if args.task in ("reset", "full"):
        reset_app()
    if args.task == "reset":
        log("")
        log("Done in %.0f seconds. The app is reset and closed." % (time.time() - started))
        return 0

    token = generate_token()
    win = register(token)
    login(win)
    open_session(win)

    log("")
    log("=" * 66)
    log("  Ready. The counter is registered, logged in and the session is open.")
    log("  Took %.1f minutes." % ((time.time() - started) / 60.0))
    log("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
