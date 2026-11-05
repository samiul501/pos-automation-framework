# ============================================================
# HELPER FUNCTIONS - generic, reusable automation utilities.
# Business logic (login, transaction, exchange, return) does NOT
# live here - that belongs in pos_actions.py.
# ============================================================

import subprocess
import time

from pywinauto import Desktop, Application
from pywinauto.keyboard import send_keys

import config


def _resolve_app_id():
    """Resolve the currently-installed app's AUMID by display name (via
    Get-StartApps) instead of relying on a hardcoded APP_ID - reinstalling
    or updating the app changes its underlying package identity (e.g. the
    publisher hash in the Package Family Name) even though the app's name
    stays the same, so a hardcoded id goes stale after every update."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-StartApps -Name '*" + config.APP_NAME + "*' | Select-Object -First 1).AppID"
            ],
            capture_output=True, text=True, timeout=15
        )
        app_id = result.stdout.strip()
        if app_id:
            return app_id
        print("Warning: Get-StartApps found no match for '" + config.APP_NAME + "', falling back to config.APP_ID")
    except Exception as e:
        print("Warning: dynamic app id lookup failed (" + str(e) + "), falling back to config.APP_ID")
    return config.APP_ID


def app_window_exists():
    """Is a POSAPP window on the desktop right now? Cheap poll that never
    raises - the UIA tree can throw mid-startup while the app is still
    building its window."""
    try:
        return any("POSAPP" in w.window_text() for w in Desktop(backend="uia").windows())
    except Exception:
        return False


def launch_app(timeout=90, retry_after=45):
    """Launch POSAPP and WAIT until its window is really there.

    This used to fire the launch and sleep a flat 5 seconds, which was the
    cause of intermittent "the exe never opened" failures: measured on this
    machine a launch takes about 17s to put a window on screen (3.7s just to
    resolve the AppID, 7.5s before the process exists), and the caller's
    get_main_window(timeout=20) then had only the remaining seconds to find
    it. A busy machine or a genuinely cold start ran past that budget and the
    whole suite failed at step one.

    So: poll for the window instead of guessing, and if nothing has appeared
    after `retry_after` seconds fire the launch once more - a shell:AppsFolder
    activation is occasionally swallowed outright, and a second one costs a
    few seconds where a failed run costs the whole suite."""
    app_id = _resolve_app_id()
    print("Launching " + config.APP_NAME + " (" + app_id + ")...")
    subprocess.run("explorer.exe shell:AppsFolder\\" + app_id, shell=True)

    start = time.time()
    relaunched = False
    while time.time() - start < timeout:
        if app_window_exists():
            print("App window appeared after %.1fs" % (time.time() - start))
            time.sleep(1.5)          # let the login screen finish painting
            return True
        if not relaunched and time.time() - start > retry_after:
            print("No window after %.0fs - firing the launch once more..." % retry_after)
            subprocess.run("explorer.exe shell:AppsFolder\\" + app_id, shell=True)
            relaunched = True
        time.sleep(1)

    raise Exception(
        "POSAPP did not open within %ds (app id %s). Check that the app is installed "
        "and that no installer/update is holding it." % (timeout, app_id))


def get_main_window(timeout=40):
    """Locate the POSAPP main window.
    If it has ended up minimized (rectangle collapses to (0,0,0,0) and any
    popups inside render off-screen at large negative coordinates), restore
    and focus it here so every caller gets a window that's actually usable -
    this was the root cause of several "button never became visible" timeouts."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            all_windows = Desktop(backend="uia").windows()
        except Exception:
            # The UIA tree can throw while the app is still starting; that is
            # not "no window", it is "not yet" - keep polling.
            time.sleep(1)
            continue
        for w in all_windows:
            if "POSAPP" not in w.window_text():
                continue
            try:
                pid = w.process_id()
                app = Application(backend="uia").connect(process=pid)
                main_win = app.window(handle=w.handle)
            except Exception:
                # Same story: connecting to a half-started process fails once
                # and works a second later.
                break
            try:
                if main_win.is_minimized():
                    main_win.restore()
                    time.sleep(0.5)
                main_win.set_focus()
            except Exception as e:
                print("Warning: could not restore/focus the main window: " + str(e))
            return main_win
        time.sleep(1)
    raise Exception("POSAPP window not found (timeout)")


def wait_and_click(element, timeout=10, desc="element"):
    """Wait for an element to become visible, then click it"""
    try:
        element.wait('visible', timeout=timeout)
    except Exception as e:
        raise Exception("'" + desc + "' did not become visible within " + str(timeout) + "s: " + str(e))
    element.click_input()


def wait_until_ready(element, timeout=10, poll_interval=0.3, desc="element"):
    """Poll until the element is enabled and visible, or timeout is reached"""
    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            if element.exists() and element.is_enabled() and element.is_visible():
                return True
        except Exception as e:
            last_error = e
        time.sleep(poll_interval)
    print("Warning: could not confirm '" + desc + "' became fully ready (" + str(last_error) + ")")
    return False


def dismiss_notification_popup(main_win, auto_id="btnNotificationOk"):
    """Click the Ok button on a 'Target Notification' popup (if it appears) after login/other actions.
    Not every build shows this popup, so instead of adding a fixed wait, this does a single
    immediate check: if present it clicks Ok, otherwise it returns False right away so the
    caller can proceed to the next step without delay."""
    ok_btn = main_win.child_window(auto_id=auto_id, control_type="Button")
    if not ok_btn.exists(timeout=0):
        return False
    ok_btn.click_input()
    time.sleep(1)
    return True


# Dialog OK/Close/Yes/No buttons across this app's popups. All are popup-only
# auto_ids (the sale screen itself never shows them), and NONE is the window's
# own title-bar close, which is "_CloseButton" WITH a leading underscore - so
# clicking any of these only ever dismisses a modal, never the app.
POPUP_BUTTON_AUTO_IDS = ("CloseButton", "PrimaryButton", "SecondaryButton", "btnNotificationOk")


def dismiss_any_popup(main_win, max_rounds=6):
    """Close ANY modal popup currently open, whatever it is ('No item
    selected', 'Customer Information Not Found', 'Login Failed', a print or
    duplicate prompt, a notification...), so a leftover popup from one step
    can never block the next. Clicks the first known dialog button it finds,
    repeating until none remain (a popup can reveal another behind it). Falls
    back to Esc. Best-effort and silent - it never raises. Returns how many
    popups it closed."""
    closed = 0
    for _ in range(max_rounds):
        found = False
        for aid in POPUP_BUTTON_AUTO_IDS:
            try:
                btn = main_win.child_window(auto_id=aid, control_type="Button")
                if btn.exists(timeout=0):
                    btn.click_input()
                    found = True
                    closed += 1
                    time.sleep(0.6)
                    break
            except Exception:
                pass
        if not found:
            break
    return closed


def wait_and_click_with_retry(main_win, auto_id, control_type, timeout=6, retries=3, retry_action=None, desc="element"):
    """Try to locate and click a button; if it doesn't appear, run retry_action() and try again"""
    for attempt in range(1, retries + 1):
        try:
            btn = main_win.child_window(auto_id=auto_id, control_type=control_type)
            btn.wait('visible', timeout=timeout)
            btn.click_input()
            return True
        except Exception:
            print("'" + desc + "' has not appeared yet (attempt " + str(attempt) + "/" + str(retries) + "), retrying...")
            if retry_action:
                try:
                    retry_action()
                except Exception as retry_e:
                    print("retry_action() itself raised: " + str(retry_e))
            time.sleep(1.5)
    raise Exception("'" + desc + "' still not found after " + str(retries) + " attempts")


def wait_and_click_first_available(main_win, auto_ids, control_type="Button", timeout=6, retries=3, retry_action=None, desc="element"):
    """Like wait_and_click_with_retry, but clicks whichever of several
    auto_ids appears first. Use this when the exact popup/button shown for
    the same action can differ between app builds (e.g. a Hold confirmation
    that changed from a Yes/No print-token question to a single OK button
    in a later build) - avoids hardcoding one build's shape and breaking on
    the next app update. Returns the auto_id that was actually clicked."""
    for attempt in range(1, retries + 1):
        start = time.time()
        while time.time() - start < timeout:
            for auto_id in auto_ids:
                btn = main_win.child_window(auto_id=auto_id, control_type=control_type)
                if btn.exists(timeout=0):
                    btn.click_input()
                    return auto_id
            time.sleep(0.3)
        print("None of " + str(auto_ids) + " ('" + desc + "') appeared yet (attempt " + str(attempt) + "/" + str(retries) + "), retrying...")
        if retry_action:
            try:
                retry_action()
            except Exception as retry_e:
                print("retry_action() itself raised: " + str(retry_e))
        time.sleep(1.5)
    raise Exception("None of " + str(auto_ids) + " ('" + desc + "') appeared after " + str(retries) + " attempts")


def press_button_robust(button, desc="button"):
    """
    Tries four methods in sequence to press a button:
    1. invoke() -- UI Automation Invoke pattern, no coordinates required
    2. click_input()
    3. focus + Enter
    4. focus + Space
    """
    try:
        button.invoke()
        print("[" + desc + "] invoke() success")
        return True
    except Exception as e:
        print("[" + desc + "] invoke() failed: " + str(e))

    try:
        button.click_input()
        print("[" + desc + "] click_input() success")
        return True
    except Exception as e:
        print("[" + desc + "] click_input() failed: " + str(e))

    try:
        button.set_focus()
        time.sleep(0.3)
        send_keys("{ENTER}")
        print("[" + desc + "] focus+Enter sent")
        return True
    except Exception as e:
        print("[" + desc + "] focus+Enter failed: " + str(e))

    try:
        button.set_focus()
        time.sleep(0.3)
        send_keys("{SPACE}")
        print("[" + desc + "] focus+Space sent")
        return True
    except Exception as e:
        print("[" + desc + "] focus+Space failed: " + str(e))

    return False


def get_latest_invoice_no(main_win):
    """Navigate to the Invoice Page and read back the invoice number of the row with the
    highest quantity (cells[3], a decimal string like "9.00"), not simply the newest row,
    since Exchange/Return need an invoice with enough quantity to work with. Used to feed a
    guaranteed-fresh invoice into the Exchange/Return flows instead of a hardcoded invoice
    number that eventually goes stale (already returned/exchanged) as the same build gets
    tested repeatedly."""
    main_win.set_focus()
    invoice_nav = main_win.child_window(auto_id="Shell_InvoicePage", control_type="ListItem")
    wait_and_click(invoice_nav, desc="Invoice Page nav item")
    time.sleep(2)

    item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
    item_grid.wait('visible', timeout=8)
    rows = item_grid.children(title="row", control_type="DataItem")
    if not rows:
        raise Exception("No invoices found on the Invoice Page")

    best_invoice_no = None
    best_qty = -1
    for row in rows:
        cells = row.children()
        try:
            qty = float(cells[3].window_text().strip())
        except (ValueError, IndexError):
            continue
        if qty > best_qty:
            best_qty = qty
            best_invoice_no = cells[1].window_text()

    if best_invoice_no is None:
        raise Exception("Could not read quantity for any invoice row on the Invoice Page")

    main_nav = main_win.child_window(auto_id="Shell_Main", control_type="ListItem")
    wait_and_click(main_nav, desc="Main nav item")
    time.sleep(2)
    return best_invoice_no


def get_most_recent_invoice_no(main_win):
    """Navigate to the Invoice Page and read back the invoice number of the very
    first row (cells[1]) - confirmed live that this grid is always ordered
    newest-first, so row 0 is the invoice that was just completed. Distinct from
    get_latest_invoice_no() above, which deliberately picks the highest-quantity
    row instead of the newest one (Exchange/Return need a "juicy" invoice, not
    necessarily the one just created). Used to capture each transaction's own
    invoice number right after payment, for later web report verification."""
    main_win.set_focus()
    invoice_nav = main_win.child_window(auto_id="Shell_InvoicePage", control_type="ListItem")
    wait_and_click(invoice_nav, desc="Invoice Page nav item")
    time.sleep(2)

    item_grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
    item_grid.wait('visible', timeout=8)
    rows = item_grid.children(title="row", control_type="DataItem")
    if not rows:
        raise Exception("No invoices found on the Invoice Page")

    most_recent_invoice_no = rows[0].children()[1].window_text()

    main_nav = main_win.child_window(auto_id="Shell_Main", control_type="ListItem")
    wait_and_click(main_nav, desc="Main nav item")
    time.sleep(2)
    return most_recent_invoice_no


def get_exchange_grid_rows(main_win):
    """Exchange and Return both use the same auto_id (conExchange)"""
    popup = main_win.child_window(auto_id="conExchange", control_type="Window")
    item_grid = popup.child_window(auto_id="ItemGridExchange", control_type="DataGrid")
    rows = item_grid.children(title="row", control_type="DataItem")
    return popup, item_grid, rows


def wait_for_stable_row_count(main_win, timeout=6, poll_interval=0.4):
    """Check how long the grid's row count stays stable"""
    start = time.time()
    last_count = -1
    stable_hits = 0
    while time.time() - start < timeout:
        _, _, rows = get_exchange_grid_rows(main_win)
        count = len(rows)
        if count == last_count and count > 0:
            stable_hits += 1
            if stable_hits >= 2:
                return count
        else:
            stable_hits = 0
        last_count = count
        time.sleep(poll_interval)
    return last_count


def select_and_click_latest_row(main_win, max_retries=4):
    """
    Finds the most recently selected row (via Ctrl+End) in the Exchange/Return
    grid and clicks it at a coordinate relative to the row's own rectangle.
    Retries with a fresh row reference each time, to avoid clicking a stale/
    wrong row due to grid virtualization.
    """
    for attempt in range(1, max_retries + 1):
        print("--- Row click attempt " + str(attempt) + "/" + str(max_retries) + " ---")

        popup, item_grid, rows = get_exchange_grid_rows(main_win)

        if len(rows) == 0:
            print("No rows found, popup already closed (item already added)")
            return True

        last_row = None
        for row in rows:
            rect = row.rectangle()
            if rect == (0, 0, 0, 0):
                continue
            try:
                if row.is_selected():
                    last_row = row
                    break
            except Exception:
                continue

        if last_row is None:
            candidates = [r for r in rows if r.rectangle() != (0, 0, 0, 0)]
            if candidates:
                last_row = max(candidates, key=lambda r: r.rectangle().top)

        if last_row is None:
            print("No valid row found, retrying Ctrl+End...")
            item_grid.click_input()
            time.sleep(0.5)
            send_keys("^{END}")
            time.sleep(1)
            continue

        rect = last_row.rectangle()
        row_width = rect.right - rect.left
        row_height = rect.bottom - rect.top

        try:
            cells = last_row.children()
            cell_texts = [c.window_text().strip() for c in cells[:3]]
            print("Target row cells: " + str(cell_texts) + " | rect: " + str(rect))
        except Exception:
            print("Target row rect: " + str(rect))

        click_offset_x = int(row_width * 0.965)
        click_offset_y = int(row_height * 0.5)

        try:
            last_row.click_input(coords=(click_offset_x, click_offset_y))
            print("Coordinate click dispatched")
        except Exception as e:
            print("Coordinate click failed: " + str(e))
            time.sleep(1)
            continue

        time.sleep(1.5)

        still_open = popup.exists() and popup.is_visible()
        if not still_open:
            print("Popup closed - item added successfully")
            return True

        _, _, new_rows = get_exchange_grid_rows(main_win)
        print("Row count after click: " + str(len(new_rows)) + " (was " + str(len(rows)) + ")")

        if len(new_rows) < len(rows):
            print("Row count decreased - item was added to the sales screen successfully")
            return True
        else:
            print("Row count unchanged, click had no effect. Retrying...")
            time.sleep(1)

    return False
