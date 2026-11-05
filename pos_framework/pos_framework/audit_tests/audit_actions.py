# ============================================================
# AUDIT ACTIONS - the exe half of the audit flow: pick an audit
# code, scan barcodes, force the sync.
#
# Mirrors pos_actions.py's role but lives here so the existing
# flows stay untouched. Reuses pos_helpers for launch/login and
# window handling - none of that is duplicated.
#
# THE AUDIT SCREEN (mapped live 2026-09-15 from the running exe)
# --------------------------------------------------------------
#   left nav ListItem name='Audit'          -> opens the screen
#   ComboBox  id='NumberBoxAuditCode'       -> approved audit codes
#   Edit      id='itemBarCode'              -> "Scan or enter Barcode (Alt+B)"
#   DataGrid  id='ItemGrid'                 -> the scanned rows
#
# Only APPROVED audits appear in the combo - an audit still
# pending approval is simply absent, which is why the web half
# must approve before this runs.
#
# SYNC: the exe pushes rows to the server automatically every 50
# rows; below that the operator forces it with Fn+F1. A test that
# scans a handful of items and skips the force-sync will find an
# empty report and blame the report.
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pos_helpers as h

from audit_tests import audit_config as acfg

from pywinauto.keyboard import send_keys


# ---- navigation ----------------------------------------------------

def open_audit_screen(main_win, timeout=15):
    """Click the left-nav 'Audit' entry.

    That ListItem has no automation id (unlike its siblings
    Shell_Main / Shell_InvoicePage / Shell_Outlet), so it can only be
    matched by name - hence title= rather than auto_id= here."""
    if is_on_audit_screen(main_win):
        return
    # The NavigationView pane can be collapsed (only icons showing), in
    # which case the "Audit" ListItem never becomes visible and pywinauto
    # surfaces a COMError from deep inside UIA. Re-acquire the window,
    # open the pane, and retry rather than fail on the first attempt.
    last = None
    for attempt in range(4):
        try:
            main_win = h.get_main_window()
            main_win.set_focus()
            item = main_win.child_window(title="Audit", control_type="ListItem")
            if attempt >= 1:
                for toggle in ("TogglePaneButton", "NavigationViewBackButton"):
                    try:
                        btn = main_win.child_window(auto_id=toggle, control_type="Button")
                        if btn.exists(timeout=1):
                            btn.click_input()
                            time.sleep(1.2)
                            break
                    except Exception:
                        pass
            h.wait_and_click(item, timeout=timeout, desc="left-nav Audit")
            time.sleep(2.5)
            if is_on_audit_screen(main_win):
                return
        except Exception as e:
            last = e
            time.sleep(2)
    raise AssertionError("could not open the Audit screen: %s" % last)


def is_on_audit_screen(main_win):
    """True if the audit screen is already showing. The breadcrumb text
    reads 'Point of Sale (POS) > Audit'; the barcode box is the more
    reliable signal since it only exists on this screen."""
    try:
        return main_win.child_window(
            auto_id="itemBarCode", control_type="Edit"
        ).exists(timeout=2)
    except Exception:
        return False


# ---- audit code ----------------------------------------------------

def list_audit_codes(main_win):
    """Every audit code the combo offers, i.e. every APPROVED, still-open
    audit for this till. Expanding leaves the dropdown open, so this
    collapses it again - a left-open popup swallows the next click."""
    combo = main_win.child_window(auto_id="NumberBoxAuditCode", control_type="ComboBox")
    combo.wait("exists visible", timeout=15)
    combo.expand()
    time.sleep(1.8)
    codes = []
    for child in combo.children():
        info = child.element_info
        if info.control_type == "ListItem":
            name = (info.name or "").strip()
            if name:
                codes.append(name)
    try:
        combo.collapse()
    except Exception:
        send_keys("{ESC}")
    time.sleep(0.8)
    return codes


def select_audit_code(main_win, code, timeout=15):
    """Pick one audit code from the dropdown.

    Raises with the list actually on offer if the code is missing -
    almost always because the setup was never approved, and a far more
    useful failure than a bare timeout on a click."""
    combo = main_win.child_window(auto_id="NumberBoxAuditCode", control_type="ComboBox")
    combo.wait("exists visible", timeout=timeout)
    combo.expand()
    time.sleep(1.8)

    available = []
    target = None
    for child in combo.children():
        info = child.element_info
        if info.control_type != "ListItem":
            continue
        name = (info.name or "").strip()
        if not name:
            continue
        available.append(name)
        if name == code:
            target = child

    if target is None:
        try:
            combo.collapse()
        except Exception:
            send_keys("{ESC}")
        raise AssertionError(
            "audit code %r is not in the dropdown (is it approved?). "
            "Available: %r" % (code, available)
        )

    target.click_input()
    time.sleep(2.5)
    return available


def selected_audit_code(main_win):
    combo = main_win.child_window(auto_id="NumberBoxAuditCode", control_type="ComboBox")
    return combo.window_text().strip()


# ---- scanning ------------------------------------------------------

def _barcode_box(main_win):
    return main_win.child_window(auto_id="itemBarCode", control_type="Edit")


def grid_row_count(main_win):
    """Rows currently in the audit grid. The grid is virtualised, so this
    counts what is realised - fine for the small scans these tests do,
    but do not trust it past a screenful; the database is the authority
    for large runs."""
    try:
        grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        return len(grid.children(title="row", control_type="DataItem"))
    except Exception:
        return 0


def grid_rows(main_win):
    """The realised grid rows as lists of cell strings, for asserting
    what the screen shows rather than only what the database got."""
    out = []
    try:
        grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
        for row in grid.children(title="row", control_type="DataItem"):
            cells = []
            for cell in row.children():
                text = (cell.element_info.name or "").strip()
                if text:
                    cells.append(text)
            out.append(cells)
    except Exception:
        pass
    return out


def scan_barcode(main_win, barcode, settle=1.0):
    """Type one barcode into the scan box and press Enter.

    Returns (row_count_before, row_count_after) so a caller can tell an
    accepted scan from a silently-ignored one. The app gives no positive
    confirmation for a successful scan, so the row delta is the signal.

    Deliberately does NOT dismiss popups - detect_popup() lets the
    caller inspect and assert on "Not an Audit Item" first."""
    before = grid_row_count(main_win)
    box = _barcode_box(main_win)
    h.wait_and_click(box, desc="audit barcode box (%s)" % barcode)
    box.type_keys(str(barcode) + "{ENTER}", pause=0.12)
    time.sleep(settle)
    return before, grid_row_count(main_win)


# The two popups this flow raises, both confirmed by the operator:
#   - an out-of-scope scan  -> "Not an Audit Item"
#   - a successful Fn+F1     -> "audit data saved successfully"
# Matching is done on lowercase fragments because the exact casing and
# punctuation differ between builds.
POPUP_NOT_AUDIT_ITEM = "not an audit item"
POPUP_SAVED = "saved successfully"

_KNOWN_POPUP_FRAGMENTS = (
    POPUP_NOT_AUDIT_ITEM,
    POPUP_SAVED,
    "item not found",
    "not found",
)


def detect_popup(main_win, timeout=2.5, require_known=False):
    """Whatever modal is on screen right now: {'text', 'buttons',
    'all_text'}, or None.

    Deliberately reports ANY modal rather than only phrases it
    recognises. An earlier version matched on "audit item" alone, which
    would have silently missed the "item not found" wording and reported
    "no popup" for a scan the app had in fact refused - the worst
    possible failure mode for a validation test, since it turns a
    working app into an apparent bug.

    Pass require_known=True to wait specifically for one of the known
    fragments (useful right after Fn+F1, where an unrelated stale label
    could otherwise satisfy the wait)."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        texts, buttons = [], []
        try:
            for child in main_win.descendants():
                info = child.element_info
                ctype = info.control_type or ""
                name = (info.name or "").strip()
                aid = info.automation_id or ""
                if ctype == "Text" and name:
                    texts.append(name)
                elif ctype == "Button" and (name or aid):
                    buttons.append({"name": name, "auto_id": aid})
        except Exception:
            pass

        known = [t for t in texts
                 if any(f in t.lower() for f in _KNOWN_POPUP_FRAGMENTS)]
        if known:
            return {"text": " | ".join(known), "all_text": texts,
                    "buttons": buttons, "known": True}

        if not require_known:
            # A modal with an acknowledge button is a popup even if its
            # wording is new to us - surface it rather than drop it.
            ack = [b for b in buttons
                   if b["auto_id"] in ("CloseButton", "PrimaryButton",
                                       "SecondaryButton", "btnNotificationOk")]
            if ack:
                last = {"text": " | ".join(texts[-4:]), "all_text": texts,
                        "buttons": buttons, "known": False}
        time.sleep(0.4)
    return last


def popup_says(popup, fragment):
    """True if a detect_popup() result mentions a fragment (case
    insensitive). Keeps tests readable and avoids each one re-lowering
    the text."""
    if not popup:
        return False
    return fragment.lower() in (popup.get("text") or "").lower()


def dismiss_popup(main_win):
    """Close whatever modal is open. Tries the ids this app uses for
    modal acknowledgement before falling back to Enter/Escape -
    'CloseButton' is the confirmed OK on the invalid-login popup, and
    'btnNotificationOk' on the target notification."""
    for auto_id in ("CloseButton", "btnNotificationOk", "PrimaryButton", "SecondaryButton"):
        try:
            button = main_win.child_window(auto_id=auto_id, control_type="Button")
            if button.exists(timeout=1):
                button.click_input()
                time.sleep(1.0)
                return auto_id
        except Exception:
            continue
    send_keys("{ENTER}")
    time.sleep(0.6)
    send_keys("{ESC}")
    time.sleep(0.6)
    return None


def scan_many(main_win, barcodes, settle=1.0, dismiss=True):
    """Scan a list of barcodes, recording what happened to each.

    Returns one dict per barcode: accepted (did the grid grow), and any
    popup text. This is the raw evidence a scope test asserts on - it
    does not decide what SHOULD have happened, which is the test's job."""
    results = []
    for barcode in barcodes:
        before, after = scan_barcode(main_win, barcode, settle=settle)
        popup = detect_popup(main_win, timeout=2.0)
        if popup and dismiss:
            dismiss_popup(main_win)
            time.sleep(0.5)
        results.append({
            "barcode": barcode,
            "rows_before": before,
            "rows_after": after,
            "accepted": after > before,
            "popup": popup["text"] if popup else None,
        })
    return results


# ---- sync ----------------------------------------------------------

def force_sync(main_win, settle=6.0, dismiss=True):
    """Push scanned rows to the server with Fn+F1.

    Needed for any scan under AUTO_SYNC_ROW_THRESHOLD (50) rows, which
    is every test here except the bulk one. The app auto-syncs at 50, so
    a bulk run may have synced already - calling this anyway is
    harmless.

    A successful save raises an "audit data saved successfully" popup
    that must be acknowledged with OK; leaving it open swallows the next
    click on the screen. Returns the popup so a test can assert the save
    was actually confirmed rather than assume the keystroke worked -
    Fn+F1 silently does nothing if focus is not on the audit screen."""
    main_win.set_focus()
    time.sleep(0.5)
    send_keys(acfg.FORCE_SYNC_KEYS)
    time.sleep(settle)
    popup = detect_popup(main_win, timeout=4.0)
    if popup and dismiss:
        dismiss_popup(main_win)
        time.sleep(0.8)
    return popup


def force_sync_and_confirm(main_win, settle=6.0):
    """Fn+F1 and insist on the success popup.

    Raises if no save confirmation appeared, so "the report is empty"
    can never be misread as a report bug when the truth is that the rows
    were never synced."""
    popup = force_sync(main_win, settle=settle, dismiss=True)
    if not popup_says(popup, POPUP_SAVED):
        raise AssertionError(
            "Fn+F1 did not produce a save confirmation; popup seen: %r"
            % (popup.get("text") if popup else None)
        )
    return popup
