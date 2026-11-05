"""One-click reproduction of the POS session-close defect.

    python reproduce_session_close_bug.py

Everything is in here: the app is reset, a fresh token is generated in the
back office, the exe is registered with it, and the reproduction flow is
then driven end to end. The verdict at the bottom compares what the server
recorded against what the exe recorded for itself.

The defect: after a logout, pressing Session Close writes ClosingDatetime
into the exe's own database and sets IsSync = 1 without the server ever
accepting the close. The cashier is shown success; the session stays open
on the server for good.

Kept out of positive_tests/ and negative_tests/ on purpose - this is a
standalone reproduction, not part of the regression suite.
"""
import argparse
import json
import os
import shutil
import sqlite3
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

SHOTS = os.path.join(HERE, "shots")
os.makedirs(SHOTS, exist_ok=True)


def _load_env():
    env = os.path.join(FRAMEWORK, ".env")
    if not os.path.exists(env):
        return
    for line in open(env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


os.environ.setdefault("DB_NAME", "DemoStore")
_load_env()

import db_helpers as db          # noqa: E402
import pos_helpers as H          # noqa: E402

# ---------------------------------------------------------------- settings

COUNTER_ID = 20183               # sami2 on devdemostore
COUNTER_NAME = "sami2"
EMPLOYEE = os.getenv("POS_USER_ID", "")      # Samiul, UserId 312
PASSWORD = os.getenv("POS_PASSWORD", "")     # both come from .env
CUSTOMER = "01700000006"         # sami4
BARCODE = "4040"                 # Boal Fish 1 (Medium), 732.00, stocked in wh 16

PKG_NAME = "CF9BD7D4-0F9A-4730-8950-05D032861D46"
PKG_FAMILY = PKG_NAME + "_6g9azff0e1qkt"
LOCALSTATE = os.path.join(os.environ["LOCALAPPDATA"], "Packages",
                          PKG_FAMILY, "LocalState")

# Registration screen: the first five on the left, the first three in the
# middle, and 4 in the Item Code Length box.
LEFT_5 = ["IsAllowSalesPerson", "IsSync", "IsPrint",
          "isDeclarationSlipPrint", "IsHoldInvoicePrint"]
MIDDLE_3 = ["IsDirectPoint", "IsItemSearch", "ViewItemDetail"]
ITEM_CODE_LENGTH = "4"


def log(*bits):
    print(*bits, flush=True)


def step(n, title):
    log("")
    log("=" * 72)
    log("STEP %s - %s" % (n, title))
    log("=" * 72)


def shot(win, name):
    path = os.path.join(SHOTS, name + ".png")
    try:
        win.capture_as_image().save(path)
    except Exception as e:
        log("   (screenshot %s failed: %s)" % (name, str(e)[:60]))
    return path


# ------------------------------------------------------------- the records

def server_sessions(n=5):
    return db._query("""
        SELECT TOP (?) CounterSessionId, SessionCode, StartDatetime,
               ClosingDatetime, ActionById, TotalInvoice, TotalSales
          FROM pos.CounterSession
         WHERE CounterId = ?
         ORDER BY CounterSessionId DESC""", [n, COUNTER_ID])


def show_server(title):
    log("")
    log("   -- server: %s" % title)
    for r in server_sessions():
        log("      #%-7s %-19s %-19s by=%-5s inv=%-4s sales=%s"
            % (r["CounterSessionId"], str(r["StartDatetime"])[:19],
               str(r["ClosingDatetime"])[:19] if r["ClosingDatetime"]
               else "** STILL OPEN **",
               r["ActionById"], r["TotalInvoice"], r["TotalSales"]))


def open_session_count():
    """How many sessions this counter is already carrying open."""
    return db._query("""SELECT COUNT(*) AS n FROM pos.CounterSession
                         WHERE CounterId = ? AND ClosingDatetime IS NULL""",
                     [COUNTER_ID])[0]["n"]


def local_snapshot():
    """A read-only copy of the exe's databases - never opened in place."""
    tmp = tempfile.mkdtemp(prefix="possnap")
    src = os.path.join(LOCALSTATE, "Database")
    for f in os.listdir(src):
        if f.endswith((".db", ".db-wal", ".db-shm")):
            shutil.copy2(os.path.join(src, f), os.path.join(tmp, f))
    return tmp


def local_session():
    """The newest session row the exe holds, plus its queue depth."""
    tmp = local_snapshot()
    path = os.path.join(tmp, "POS.1.01.db")
    cn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cn.row_factory = sqlite3.Row
    row = cn.execute(
        "SELECT * FROM CounterSession ORDER BY rowid DESC LIMIT 1").fetchone()
    queue = cn.execute("SELECT COUNT(*) FROM tblDataLog WHERE isSync = 0").fetchone()[0]
    cn.close()

    logs = None
    alog = os.path.join(LOCALSTATE, "AppLog", "AppLog.1.0.db")
    if os.path.exists(alog):
        t2 = os.path.join(tempfile.mkdtemp(), "a.db")
        shutil.copy2(alog, t2)
        c2 = sqlite3.connect("file:%s?mode=ro" % t2.replace("\\", "/"), uri=True)
        try:
            logs = c2.execute("SELECT COUNT(*) FROM Logs").fetchone()[0]
        except Exception:
            pass
        c2.close()
    return (dict(row) if row else None), queue, logs


# --------------------------------------------------------- 1. reset the app

def reset_app():
    step(1, "reset the installed application")
    full = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-AppxPackage -Name '%s').PackageFullName" % PKG_NAME],
        capture_output=True, text=True, timeout=120).stdout.strip()
    log("   package: %s" % full)
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process -Name '*POSAPP*' -ErrorAction SilentlyContinue "
         "| Stop-Process -Force; Start-Sleep 3; Reset-AppxPackage -Package '%s'" % full],
        capture_output=True, text=True, timeout=300)
    time.sleep(6)
    left = os.listdir(LOCALSTATE) if os.path.isdir(LOCALSTATE) else []
    log("   LocalState after the reset: %s" % (left or "(empty)"))
    if left:
        log("   WARNING: the reset left files behind")


# ------------------------------------------- 2. token, from the back office

def generate_token():
    step(2, "generate a fresh token in the back office")
    from backoffice.profiles import registry
    from backoffice.pages.login_page import LoginPage
    profile = registry.get("demostore")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1800, "height": 1100})
        page = ctx.new_page()
        page.set_default_navigation_timeout(120000)
        page.set_default_timeout(60000)
        page.goto(profile.base_url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(6000)
        if page.locator("#loginMobileNo").count():
            LoginPage(page, profile).login()
            page.wait_for_timeout(8000)
        log("   signed in to %s" % profile.base_url)

        def menu(label, wait):
            entry = page.locator(".menuContent", has_text=label).first
            if not entry.count():
                entry = page.get_by_text(label, exact=True).first
            entry.click(force=True)
            page.wait_for_timeout(wait)

        menu("POS", 2500)
        menu("Setup", 4000)
        menu("Counter Setup", 11000)

        box = page.get_by_placeholder("Search", exact=False)
        if box.count():
            box.first.click(force=True)
            box.first.fill(COUNTER_NAME)
            page.keyboard.press("Enter")
            page.wait_for_timeout(8000)

        row = page.locator("table tbody tr", has_text=COUNTER_NAME).first
        assert row.count(), "%s is not on the counter list" % COUNTER_NAME
        # The action is plain text inside its own cell, not a <button>.
        row.locator("td", has_text="Generate Token").last.click(force=True)
        page.wait_for_timeout(5000)

        page.get_by_role("button", name="Generate New", exact=False).first.click(force=True)
        page.wait_for_timeout(10000)

        text = page.locator("[role='dialog'] p, [class*='MuiDialogContent'] p").first.inner_text()
        token = text.split(":", 1)[1].strip() if ":" in text else text.strip()
        browser.close()

    row = db._query("SELECT Token, LastTokenGeneratedDate FROM pos.POSCounter "
                    "WHERE CounterId = ?", [COUNTER_ID])[0]
    log("   token: %d characters, generated %s" % (len(token),
                                                   str(row["LastTokenGeneratedDate"])[:19]))
    assert token.startswith(str(row["Token"])[:60]), \
        "the token on screen does not match the one stored on the counter"
    json.dump({"counter": COUNTER_ID, "token": token},
              open(os.path.join(HERE, "token.json"), "w"), indent=2)
    return token


# ------------------------------------------------------- 3. register the exe

def to_clipboard(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def click_ok(win, titles=("OK", "Ok", "Yes", "No", "Cancel"), timeout=2):
    """Popups here only respond to their own button - Enter does nothing."""
    for t in titles:
        b = win.child_window(title=t, control_type="Button")
        if b.exists(timeout=timeout) and b.is_visible():
            b.click_input()
            time.sleep(2)
            return t
    return None


def register_exe(token):
    step(3, "register the exe against %s" % COUNTER_NAME)
    H.launch_app()
    win = H.get_main_window()
    time.sleep(3)

    reg = win.child_window(auto_id="btnRegistration", control_type="Button")
    if reg.exists(timeout=5):
        reg.click_input()
        time.sleep(6)

    box = win.child_window(auto_id="txtToken", control_type="Edit")
    box.wait("visible", timeout=40)
    box.click_input()
    time.sleep(1)
    # 2112 characters, and the control exposes no ValuePattern - paste it.
    to_clipboard(token)
    send_keys("^a")
    send_keys("^v")
    time.sleep(3)
    log("   token pasted")

    for auto_id in LEFT_5 + MIDDLE_3:
        cb = win.child_window(auto_id=auto_id, control_type="CheckBox")
        cb.wait("visible", timeout=15)
        if cb.get_toggle_state() != 1:
            cb.click_input()
            time.sleep(0.4)
    log("   ticked: %s" % ", ".join(LEFT_5 + MIDDLE_3))

    length = win.child_window(auto_id="txtItemCodeLength", control_type="Edit")
    length.set_focus()
    length.set_edit_text(ITEM_CODE_LENGTH)
    time.sleep(1)
    log("   item code length: %s" % ITEM_CODE_LENGTH)
    shot(win, "01-registration-filled")

    win.child_window(title="Save", control_type="Button").click_input()
    time.sleep(6)
    click_ok(win, ("OK", "Ok"), timeout=10)      # "Successfully Created"
    shot(win, "02-registered")

    go = win.child_window(title="Go To Login", control_type="Button")
    if go.exists(timeout=5):
        go.click_input()
        time.sleep(8)
    log("   registered")
    return win


# -------------------------------------------------------------- the exe flow

def login(win, user=EMPLOYEE, pwd=PASSWORD):
    u = win.child_window(auto_id="userName", control_type="Edit")
    u.wait("visible", timeout=60)
    u.click_input()
    send_keys("^a")
    u.type_keys(user, with_spaces=True)
    p = win.child_window(auto_id="UserPassword", control_type="Edit")
    p.click_input()
    send_keys("^a")
    p.type_keys(pwd, with_spaces=True)
    time.sleep(1)
    win.child_window(auto_id="btnLogin", control_type="Button").click_input()
    time.sleep(15)
    click_ok(win)
    log("   %s" % win.child_window(auto_id="AppTitleBarText").window_text())


def wait_processing(win, limit=900):
    end = time.time() + limit
    while time.time() < end:
        if not win.child_window(auto_id="StatusText",
                                control_type="Text").exists(timeout=1):
            return True
        time.sleep(10)
    return False


def counter_selected(win):
    """The chosen counter shows up as a label inside the combo, not as its
    window_text - so look for the label."""
    lbl = win.child_window(auto_id="cmbo_market_ID", control_type="Text")
    return lbl.exists(timeout=1) and COUNTER_NAME in (lbl.window_text() or "")


def open_session(win):
    win.child_window(auto_id="Shell_Outlet", control_type="ListItem").click_input()
    time.sleep(6)

    cmb = win.child_window(auto_id="cmbCusto", control_type="ComboBox")
    cmb.wait("visible", timeout=30)
    for attempt in range(3):
        if counter_selected(win):
            break
        cmb.click_input()
        time.sleep(3)
        item = win.child_window(title=COUNTER_NAME, control_type="ListItem")
        if item.exists(timeout=5):
            item.click_input()
            time.sleep(3)
    assert counter_selected(win), "could not select counter %s" % COUNTER_NAME
    log("   counter selected: %s" % COUNTER_NAME)

    win.child_window(title="Open Session", control_type="Button").click_input()
    time.sleep(4)

    # "Let's Start" carries a typographic apostrophe, so go by auto_id and
    # wait for the opening dialog to actually be on screen.
    start = win.child_window(auto_id="PrimaryButton", control_type="Button")
    start.wait("visible", timeout=30)
    log("   opening dialog: %r" % start.window_text())
    start.click_input()
    time.sleep(10)

    wait_processing(win)
    time.sleep(5)
    click_ok(win)
    win.set_focus()
    send_keys("{ENTER}")
    time.sleep(3)
    click_ok(win)


def transaction(win, customer=CUSTOMER, barcode=BARCODE):
    win.set_focus()
    f = win.child_window(auto_id="txtCustomer", control_type="Edit")
    f.click_input()
    f.type_keys(customer + "{ENTER}", pause=0.15)
    time.sleep(2)

    grp = win.child_window(auto_id="asbItemSearch", control_type="Group")
    box = grp.child_window(auto_id="TextBox", control_type="Edit")
    box.click_input()
    box.type_keys(barcode + "{ENTER}", pause=0.12)
    time.sleep(2)

    total = win.child_window(auto_id="GrandTotal", control_type="Text").window_text()
    log("   cart total: %s" % total)
    assert total not in ("0.00", "0", ""), \
        "nothing landed in the cart - barcode %s may be out of stock here" % barcode

    box.click_input()
    time.sleep(0.5)
    send_keys("{ENTER}")
    time.sleep(2)
    cash = win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
    cash.click_input()
    time.sleep(1)
    send_keys("{ENTER}")
    time.sleep(2)
    win.set_focus()
    send_keys("{ENTER}")
    time.sleep(2)

    no = win.child_window(auto_id="SecondaryButton", control_type="Button")
    if no.exists(timeout=25):
        no.click_input()          # "No" to the print prompt
        time.sleep(2)
    click_ok(win, ("OK", "Ok"), timeout=10)      # "Invoice Created Successfully"
    time.sleep(2)
    click_ok(win)
    return total


def logout(win):
    win.child_window(auto_id="btnLogOut", control_type="Button").click_input()
    time.sleep(4)
    b = win.child_window(title="Logout", control_type="Button")
    if b.exists(timeout=8):
        b.click_input()
        time.sleep(12)


def session_close(win):
    """Lock Session -> Session Close -> authorise -> Close Session.

    The authorise overlay appears *after* Session Close, not before.
    """
    win.set_focus()
    lock = win.child_window(title="Lock Session (Alt + L)", control_type="Text")
    if lock.exists(timeout=5):
        lock.click_input()
    else:
        send_keys("%l")
    time.sleep(4)
    shot(win, "06-lock-prompt")

    btn = win.child_window(title="Session Close", control_type="Button")
    btn.wait("visible", timeout=20)
    btn.click_input()
    time.sleep(8)

    u = win.child_window(auto_id="userName", control_type="Edit")
    if u.exists(timeout=5):
        log("   it asks to authorise again - giving the same credentials")
        u.click_input()
        send_keys("^a")
        u.type_keys(EMPLOYEE, with_spaces=True)
        p = win.child_window(auto_id="UserPassword", control_type="Edit")
        p.click_input()
        send_keys("^a")
        p.type_keys(PASSWORD, with_spaces=True)
        time.sleep(1)
        win.child_window(auto_id="AuthorizeLogin",
                         control_type="Button").click_input()
        time.sleep(12)
    shot(win, "07-closing-screen")

    close = win.child_window(title="Close Session", control_type="Button")
    close.wait("visible", timeout=25)
    log("   pressing Close Session")
    close.click_input()
    time.sleep(8)

    for w in win.descendants(control_type="Text"):
        try:
            n = (w.element_info.name or "").strip()
        except Exception:
            continue
        if n and len(n) < 90 and any(k in n.lower() for k in
                                     ("success", "not found", "error",
                                      "active session")):
            log("   screen says: %r" % n)
    click_ok(win, ("OK", "Ok", "Yes"), timeout=4)
    time.sleep(5)
    shot(win, "08-after-close")


# ------------------------------------------------------------- the verdict

def verdict(session_id):
    step(9, "verdict - the server against the exe's own books")
    time.sleep(6)
    srv = db._query("""SELECT CounterSessionId, StartDatetime, ClosingDatetime,
                              TotalInvoice, TotalSales
                         FROM pos.CounterSession WHERE CounterSessionId = ?""",
                    [session_id])
    srv = srv[0] if srv else None
    loc, queue, logs = local_session()

    log("")
    log("   server  #%s" % session_id)
    log("      ClosingDatetime  %s" % (srv["ClosingDatetime"] if srv and
                                       srv["ClosingDatetime"] else "NULL  <-- still open"))
    log("      TotalInvoice     %s" % (srv["TotalInvoice"] if srv else "?"))
    log("      TotalSales       %s" % (srv["TotalSales"] if srv else "?"))
    log("")
    log("   exe's own database")
    log("      SessionCode            %s" % (loc or {}).get("SessionCode"))
    log("      ClosingDatetime        %s" % (loc or {}).get("ClosingDatetime"))
    log("      IsSync                 %s" % (loc or {}).get("IsSync"))
    log("      UserIdForSessionClose  %s" % (loc or {}).get("UserIdForSessionClose"))
    log("      unsent rows in queue   %s" % queue)
    log("      AppLog rows            %s" % logs)

    server_closed = bool(srv and srv["ClosingDatetime"])
    local_closed = bool(loc and loc.get("ClosingDatetime") not in (None, "", "None"))

    log("")
    log("   " + "-" * 66)
    if local_closed and not server_closed:
        log("   VERDICT: BUG REPRODUCED")
        log("   The exe recorded the close and marked it synced; the server")
        log("   never received it, and nothing is queued to retry.")
        code = 1
    elif server_closed and local_closed:
        log("   VERDICT: NOT REPRODUCED - the close reached the server.")
        code = 0
    else:
        log("   VERDICT: INCONCLUSIVE - server closed=%s, exe closed=%s"
            % (server_closed, local_closed))
        code = 2
    log("   " + "-" * 66)
    return code


# ------------------------------------------------------------------- driver

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-setup", action="store_true",
                    help="reuse the current registration instead of resetting")
    args = ap.parse_args()

    started = time.time()
    log("Reproducing the POS session-close defect")
    log("counter %s (%s), employee %s" % (COUNTER_NAME, COUNTER_ID, EMPLOYEE))

    if args.skip_setup:
        log("")
        log("(setup skipped - using the current registration)")
        H.launch_app()
        win = H.get_main_window()
        time.sleep(3)
        click_ok(win)
    else:
        reset_app()
        token = generate_token()
        win = register_exe(token)

    step(4, "log in as %s" % EMPLOYEE)
    login(win)

    step(5, "open a session on %s" % COUNTER_NAME)
    already = open_session_count()
    log("   the counter is already carrying %d session(s) left open" % already)
    before = {r["CounterSessionId"] for r in server_sessions(10)}
    open_session(win)
    shot(win, "03-session-open")
    # The row can take a moment to land, so give it a little while.
    new = []
    for _ in range(12):
        new = [r for r in server_sessions(10)
               if r["CounterSessionId"] not in before]
        if new:
            break
        time.sleep(5)

    if not new:
        # The open never reached the server either. The exe normally still
        # holds a local row for it - that row is the whole diagnosis.
        loc, queue, logs = local_session()
        log("")
        log("   The exe believes it opened a session, but the server has no row.")
        log("      SessionCode      %s" % (loc or {}).get("SessionCode"))
        log("      StartDatetime    %s" % (loc or {}).get("StartDatetime"))
        log("      IsSync           %s" % (loc or {}).get("IsSync"))
        log("      sessions already left open on this counter: %d" % already)
        log("")
        log("   VERDICT: OPEN SESSION ALSO LOST")
        log("   Clear the open sessions on this counter and run again to test"
            " the close.")
        return 3
    session_id = new[0]["CounterSessionId"]
    log("   session #%s opened at %s"
        % (session_id, str(new[0]["StartDatetime"])[:19]))
    show_server("session opened")

    step(6, "one sale")
    transaction(win)
    shot(win, "04-sale")

    step(7, "LOG OUT without closing - this is the trigger")
    logout(win)
    shot(win, "05-logged-out")
    log("   logged out; session #%s is still open on the server" % session_id)

    step(8, "the same employee logs back in, then closes the session")
    login(win)
    session_close(win)

    code = verdict(session_id)
    log("")
    log("done in %.1f minutes; screenshots in %s"
        % ((time.time() - started) / 60.0, SHOTS))
    return code


if __name__ == "__main__":
    sys.exit(main())
