"""POS exe multi-sale LOAD TEST - online or offline, one entry point.

Runs N customers x M items per sale through the POSAPP exe, the same way in
both modes. It is defensive about the two popups that interrupt a large sale:

  * "Multiple Item List's" (a barcode/code that matches several variants)
      -> Close and skip that code
  * "Out Of Stock !" (online only - offline does not block OOS)
      -> dismiss and skip that code

and it never types a barcode on top of a leftover one: the search box is cleared
before every entry, and the cart (ItemGrid) row count is checked after each add
so only real additions are counted. It draws from a larger item pool until each
sale holds exactly ITEMS_PER_SALE lines.

Run it:
    python load_test.py                      # defaults (see below)
    python load_test.py --mode offline
    python load_test.py --customers 4 --items 30 --mode online

Or double-click run_load_test.bat for a one-click run with the defaults.
Config (item pool / customers) lives in load_test_items.json and
load_test_customers.json next to this file.
"""
import argparse
import io
import json
import os
import time
import traceback

from pywinauto.keyboard import send_keys

import config
import pos_actions as a
import pos_helpers as h

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "load_test_shots")
os.makedirs(SHOTS, exist_ok=True)


def _load(name, fallback):
    p = os.path.join(HERE, name)
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return fallback


ITEM_POOL = _load("load_test_items.json", [])
CUSTOMERS = _load("load_test_customers.json", [])


def log(*b):
    print(*b, flush=True)


def shot(name):
    try:
        h.get_main_window().capture_as_image().save(os.path.join(SHOTS, name + ".png"))
    except Exception:
        pass


# ---------- exe helpers ----------

def cart_rows():
    """Current number of lines in the sale cart (the main ItemGrid)."""
    try:
        g = h.get_main_window().child_window(auto_id="ItemGrid", control_type="DataGrid")
        return len(g.children(title="row", control_type="DataItem"))
    except Exception:
        return -1


def _has_text(needle):
    mw = h.get_main_window()
    for t in mw.descendants(control_type="Text"):
        try:
            if needle.lower() in (t.window_text() or "").lower():
                return True
        except Exception:
            pass
    return False


def _click_button_named(name):
    mw = h.get_main_window()
    for b in mw.descendants(control_type="Button"):
        try:
            if (b.window_text() or "").strip().lower() == name.lower():
                b.click_input()
                return True
        except Exception:
            pass
    return False


def _dismiss_oos():
    """Out-of-stock popup (online): try the usual dismiss buttons, else Enter/Esc."""
    mw = h.get_main_window()
    for aid in ("CloseButton", "PrimaryButton", "SecondaryButton", "btnNotificationOk"):
        try:
            btn = mw.child_window(auto_id=aid, control_type="Button")
            if btn.exists(timeout=1):
                btn.click_input()
                return
        except Exception:
            pass
    if not _click_button_named("OK"):
        send_keys("{ENTER}")
    time.sleep(0.5)
    send_keys("{ESC}")


def add_until(isb, want):
    """Add items from the pool until the cart holds `want` lines.
    Returns (added, skipped[list of (code, reason)])."""
    added, i, skipped = 0, 0, []
    while added < want and i < len(ITEM_POOL):
        bc = ITEM_POOL[i]
        i += 1
        before = cart_rows()
        h.wait_and_click(isb, desc="item box")
        send_keys("^a{BACKSPACE}")                 # clear before typing (no concat)
        isb.type_keys(bc + "{ENTER}", pause=0.08)
        time.sleep(1.2)

        if _has_text("Multiple Item"):             # variant popup
            if not _click_button_named("Close"):
                send_keys("{ESC}")
            time.sleep(0.8)
            skipped.append((bc, "variant"))
            continue
        if _has_text("Out Of Stock"):              # online OOS popup
            _dismiss_oos()
            time.sleep(0.8)
            skipped.append((bc, "out-of-stock"))
            continue

        after = cart_rows()
        if after > before:
            added = after
        else:
            time.sleep(1)
            if cart_rows() > before:
                added = cart_rows()
            else:
                skipped.append((bc, "no-add"))
    return added, skipped


def pay_and_close(isb):
    mw = h.get_main_window()
    mw.set_focus()
    h.wait_and_click(isb, desc="item box (to cash)")
    time.sleep(0.4)
    send_keys("{ENTER}")
    time.sleep(2)
    cash = mw.child_window(auto_id="textBoxCashAmount", control_type="Edit")
    h.wait_and_click(cash, desc="cash")
    time.sleep(1)
    send_keys("{ENTER}")
    time.sleep(2)
    mw.set_focus()
    send_keys("{ENTER}")                            # trigger print
    time.sleep(2)
    no = mw.child_window(auto_id="SecondaryButton", control_type="Button")
    h.wait_and_click(no, timeout=60, desc="Print popup No")
    time.sleep(1.5)
    send_keys("{ENTER}")                            # invoice created OK
    time.sleep(2)


def set_customer(cust):
    mw = h.get_main_window()
    cf = mw.child_window(auto_id="txtCustomer", control_type="Edit")
    h.wait_and_click(cf, desc="customer")
    send_keys("^a{BACKSPACE}")
    cf.type_keys(cust + "{ENTER}", pause=0.15)
    time.sleep(2)


def _wait_for(auto_id, timeout=40):
    """Poll until a control with this auto_id is present; the UIA tree can throw
    transiently while the exe transitions, so this swallows and keeps trying."""
    for _ in range(timeout):
        try:
            mw = h.get_main_window()
            if mw.child_window(auto_id=auto_id, control_type="Edit").exists(timeout=1):
                return mw
        except Exception:
            pass
        time.sleep(1)
    return None


def _login_once(mode):
    h.launch_app()
    time.sleep(2)
    for _ in range(4):
        send_keys("{ESC}")
        time.sleep(0.4)
    mw = h.get_main_window()
    # already logged in? log out so we can choose the mode on the login screen
    try:
        if mw.child_window(auto_id="txtCustomer", control_type="Edit").exists(timeout=4):
            a.do_logout(mw)
            time.sleep(3)
    except Exception:
        pass
    mw = _wait_for("userName", 40)
    if mw is None:
        raise Exception("login screen (userName) never appeared")
    time.sleep(1)
    uf = mw.child_window(auto_id="userName", control_type="Edit")
    h.wait_and_click(uf, timeout=20, desc="user")
    send_keys("^a{BACKSPACE}")
    uf.type_keys(config.USER_ID, pause=0.05)
    pf = mw.child_window(auto_id="UserPassword", control_type="Edit")
    h.wait_and_click(pf, timeout=20, desc="password")
    pf.type_keys(config.PASSWORD, pause=0.05)
    cb = mw.child_window(auto_id="IsOffline", control_type="CheckBox")
    want_offline = (mode == "offline")
    if cb.exists(timeout=3) and cb.get_toggle_state() != (1 if want_offline else 0):
        cb.click_input()
        time.sleep(1)
    log("mode=%s  (IsOffline toggle=%s)" % (mode, cb.get_toggle_state() if cb.exists() else "n/a"))
    mw.child_window(auto_id="btnLogin", control_type="Button").click_input()
    time.sleep(6)
    mw = h.get_main_window()
    h.dismiss_notification_popup(mw)
    if _wait_for("txtCustomer", 20) is None:
        raise Exception("login did not reach the sale screen")


def login(mode, attempts=3):
    last = None
    for i in range(attempts):
        try:
            _login_once(mode)
            return
        except Exception as e:
            last = e
            log("   login attempt %d/%d failed: %s" % (i + 1, attempts, str(e)[:70]))
            time.sleep(4)
    raise last


def run(mode, n_customers, n_items):
    log("=== POS LOAD TEST  mode=%s  customers=%d  items/sale=%d ===" % (mode, n_customers, n_items))
    if len(ITEM_POOL) < n_items:
        log("WARNING: item pool (%d) smaller than items/sale (%d)" % (len(ITEM_POOL), n_items))
    custs = (CUSTOMERS * ((n_customers // max(len(CUSTOMERS), 1)) + 1))[:n_customers]
    login(mode)
    log("logged in")
    results = []
    for idx, cust in enumerate(custs, 1):
        log("")
        log("--- SALE %d / %d  customer=%s ---" % (idx, n_customers, cust))
        t0 = time.time()
        try:
            set_customer(cust)
            isg = h.get_main_window().child_window(auto_id="asbItemSearch", control_type="Group")
            isb = isg.child_window(auto_id="TextBox", control_type="Edit")
            added, skipped = add_until(isb, n_items)
            log("   cart=%d  skipped=%s" % (added, skipped[:8]))
            shot("%s-sale%d-cart" % (mode, idx))
            if added >= n_items:
                pay_and_close(isb)
                dt = time.time() - t0
                log("   SALE %d OK  (%d items, %.0fs)" % (idx, added, dt))
                results.append((cust, "OK", added, "%.0fs" % dt))
            else:
                log("   SALE %d SHORT - only %d items, not paid" % (idx, added))
                results.append((cust, "SHORT", added, ""))
                for _ in range(4):
                    send_keys("{ESC}")
                    time.sleep(0.4)
        except Exception as e:
            log("   SALE %d FAIL: %s" % (idx, str(e)[:120]))
            traceback.print_exc()
            shot("%s-sale%d-FAIL" % (mode, idx))
            results.append((cust, "FAIL", -1, str(e)[:60]))
            for _ in range(5):
                send_keys("{ESC}")
                time.sleep(0.4)

    log("")
    log("=== SUMMARY  (mode=%s) ===" % mode)
    ok = sum(1 for r in results if r[1] == "OK")
    for r in results:
        log("   %-14s %-6s items=%s %s" % (r[0], r[1], r[2], r[3]))
    log("   %d/%d sales completed" % (ok, n_customers))
    log("   NOTE: in offline mode these sales sync to the server when the exe next goes online.")
    return results


def main():
    ap = argparse.ArgumentParser(description="POS exe load test (online/offline)")
    ap.add_argument("--mode", choices=["online", "offline"], default="online")
    ap.add_argument("--customers", type=int, default=4)
    ap.add_argument("--items", type=int, default=30)
    args = ap.parse_args()
    run(args.mode, args.customers, args.items)


if __name__ == "__main__":
    main()
