# ============================================================
# CREDIT ACTIONS - the exe half of the credit-sales flow:
# read the Sales Collection screen, and sell on credit.
#
# Mirrors pos_actions.py's role but lives here so the existing
# flows stay untouched. Reuses pos_helpers for launch/login and
# window handling - none of that is duplicated.
#
# THE SALES COLLECTION SCREEN (mapped live 2026-09-22)
# ------------------------------------------------------
#   left nav ListItem  id='Shell_CreditCollection'
#   Edit               id='txtSearchCreditInvoice'  (number + Enter)
#   DataGrid           id='ItemGrid'   the outstanding invoices
#   RadioButton        id='rdiCash' / 'rdiBank' / 'rdiWallet'
#   Edit               id='txtRemarks' / 'txtCollectionAmount'
#   Button             id='Save'
#
# The four cards (Credit Limit, Pending Due, Remaining Credit,
# Credit Days) have NO automation id at all. They are read by
# walking every Text element in order and taking the value that
# FOLLOWS each label - which is why read_collection_cards()
# looks the way it does. Nothing on this screen except the search
# box renders until a customer has been searched.
#
# SELLING ON CREDIT - three things that are easy to get wrong
# ------------------------------------------------------------
# 1. The Payment Type combo is id='cmbSpcPromg1' (the name is
#    misleading - it is not a promo box). Clicking an option in
#    it does NOT select anything, and window_text() stays ''
#    forever, so a click-and-hope leaves the sale as CASH. The
#    working route is the item's own select pattern, verified
#    with selected_text().
# 2. After typing the amount and pressing the + button
#    (id='btnWalletAdd'), a "Reference No" popup appears
#    (Edit id='WallateReferance'). The payment line is NOT added
#    until that is filled and Enter pressed.
# 3. Completing the sale raises TWO popups in a row:
#    "Would you like to print?" (No = SecondaryButton) and then
#    an invoice-created OK (PrimaryButton).
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pos_helpers as h
import pos_actions as a

from credit_tests import credit_config as ccfg

from pywinauto.keyboard import send_keys


CARD_LABELS = ("Customer Name", "Mobile No", "Credit Limit", "Pending Due",
               "Remaining Credit", "Credit Days")

PAYMENT_TYPE_COMBO = "cmbSpcPromg1"
PAYMENT_AMOUNT_BOX = "textBoxWalletAmount"
PAYMENT_ADD_BUTTON = "btnWalletAdd"
PAYMENT_REFERENCE_BOX = "WallateReferance"
PAYMENT_GRID = "paymentGrid1"
CREDIT_SALES_OPTION = "Credit Sales"


# ---- session --------------------------------------------------------

def ensure_logged_in():
    """Returns the main window, launching and logging in only if needed -
    so the suite can run against an exe a tester already has open."""
    try:
        main_win = h.get_main_window(timeout=5)
    except Exception:
        h.launch_app()
        time.sleep(6)
        main_win = h.get_main_window(timeout=40)
    if main_win.child_window(auto_id="userName", control_type="Edit").exists(timeout=3):
        a.do_login()
        main_win = h.get_main_window()
    h.dismiss_notification_popup(main_win)
    return main_win


def open_sale_screen(main_win):
    main_win.set_focus()
    time.sleep(0.4)
    main_win.child_window(auto_id="Shell_Main", control_type="ListItem").click_input()
    time.sleep(3)
    return h.get_main_window()


def open_sales_collection(main_win):
    """The screen is labelled "Sales Collection" but its nav item is still
    called Shell_CreditCollection."""
    main_win.set_focus()
    time.sleep(0.4)
    main_win.child_window(auto_id="Shell_CreditCollection", control_type="ListItem").click_input()
    time.sleep(4)
    return h.get_main_window()


# ---- Sales Collection: read ----------------------------------------

def _ordered_texts(main_win):
    """Every non-empty Text on screen, in tree order, with consecutive
    duplicates collapsed (this app renders each label twice)."""
    out = []
    for t in main_win.descendants(control_type="Text"):
        try:
            v = (t.window_text() or "").strip()
        except Exception:
            continue
        if v and (not out or out[-1] != v):
            out.append(v)
    return out


def search_customer(main_win, mobile_no, settle=5):
    """Type a customer number into Sales Collection and wait for the cards."""
    box = main_win.child_window(auto_id="txtSearchCreditInvoice", control_type="Edit")
    h.wait_and_click(box, desc="Sales Collection search box")
    box.type_keys("^a{DELETE}")
    time.sleep(0.3)
    box.type_keys(mobile_no, pause=0.05)
    send_keys("{ENTER}")
    time.sleep(settle)
    return h.get_main_window()


def read_collection_cards(main_win):
    """{label: value} for the six header fields. A label with no value
    after it comes back as None rather than raising, so a half-rendered
    screen is reported as a mismatch instead of a crash."""
    texts = _ordered_texts(main_win)
    cards = {}
    for label in CARD_LABELS:
        if label in texts:
            i = texts.index(label)
            cards[label] = texts[i + 1] if i + 1 < len(texts) else None
        else:
            cards[label] = None
    return cards


def read_collection_grid(main_win):
    """The outstanding-invoice rows as dicts. Column order was read off
    the live grid: SL, Invoice No, Inv Date, Due Date, Remaining Days,
    Quantity, Pending Amt, Receive Amt, Collection Amt, Status."""
    keys = ["sl", "invoice_no", "inv_date", "due_date", "remaining_days",
            "quantity", "pending_amt", "receive_amt", "collection_amt", "status"]
    grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
    if not grid.exists(timeout=5):
        return []
    rows = []
    for row in grid.children(title="row", control_type="DataItem"):
        cells = []
        for c in row.children():
            try:
                cells.append((c.window_text() or "").strip())
            except Exception:
                cells.append("")
        rows.append(dict(zip(keys, cells)))
    return rows


# ---- the sale -------------------------------------------------------

def add_customer_and_item(main_win, mobile_no, barcode):
    """Customer + one item on the sale screen. Returns the item search box
    (the rest of the flow needs it)."""
    customer_field = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
    h.wait_and_click(customer_field, desc="Customer field")
    customer_field.type_keys("^a{DELETE}")
    customer_field.type_keys(mobile_no + "{ENTER}", pause=0.15)
    time.sleep(2.5)

    group = main_win.child_window(auto_id="asbItemSearch", control_type="Group")
    box = group.child_window(auto_id="TextBox", control_type="Edit")
    h.wait_and_click(box, desc="Item search box")
    box.type_keys(barcode + "{ENTER}", pause=0.15)
    h.wait_until_ready(box, timeout=8, poll_interval=0.3, desc="Item search box (after item)")
    time.sleep(1.5)
    return box


def cart_rows(main_win):
    grid = main_win.child_window(auto_id="ItemGrid", control_type="DataGrid")
    return grid.children(title="row", control_type="DataItem")


def grand_total(main_win):
    return (main_win.child_window(auto_id="GrandTotal", control_type="Text").window_text() or "").strip()


def select_credit_sales(main_win, attempts=3):
    """Pick "Credit Sales" in the Payment Type combo and PROVE it stuck.

    Clicking the option does nothing and window_text() is always '' - the
    only thing that works is expanding the combo and calling select() on
    the option item, then reading selected_text(). Without the check a
    failed pick silently completes the sale as cash, which is exactly the
    bug this suite exists to catch."""
    for attempt in range(1, attempts + 1):
        combo = main_win.child_window(auto_id=PAYMENT_TYPE_COMBO, control_type="ComboBox")
        combo.expand()
        time.sleep(1.2)
        items = combo.descendants(control_type="ListItem")
        match = next((i for i in items if (i.window_text() or "").strip() == CREDIT_SALES_OPTION), None)
        if match is None:
            options = [(i.window_text() or "").strip() for i in items]
            raise AssertionError("no %r option in the Payment Type combo; options: %r"
                                 % (CREDIT_SALES_OPTION, options))
        try:
            match.select()
        except Exception:
            match.click_input()
        time.sleep(1.2)

        combo = h.get_main_window().child_window(auto_id=PAYMENT_TYPE_COMBO, control_type="ComboBox")
        try:
            chosen = combo.selected_text()
        except Exception:
            chosen = None
        if chosen == CREDIT_SALES_OPTION:
            return True
        print("Payment Type still %r after attempt %d/%d, retrying..." % (chosen, attempt, attempts))
    raise AssertionError("Payment Type could not be set to %r - the sale would go through as CASH"
                         % CREDIT_SALES_OPTION)


def add_credit_payment(main_win, amount, reference="1"):
    """Type the amount, press +, answer the Reference No popup. Returns the
    payment-grid rows afterwards - empty means the line was NOT added."""
    box = main_win.child_window(auto_id=PAYMENT_AMOUNT_BOX, control_type="Edit")
    h.wait_and_click(box, desc="Credit amount box")
    box.type_keys("^a{DELETE}")
    time.sleep(0.3)
    box.type_keys(str(amount), pause=0.08)
    time.sleep(0.6)

    main_win.child_window(auto_id=PAYMENT_ADD_BUTTON, control_type="Button").click_input()
    time.sleep(2.5)

    main_win = h.get_main_window()
    ref = main_win.child_window(auto_id=PAYMENT_REFERENCE_BOX, control_type="Edit")
    if ref.exists(timeout=6):
        ref.click_input()
        ref.type_keys("^a{DELETE}")
        time.sleep(0.3)
        ref.type_keys(str(reference), pause=0.1)
        time.sleep(0.4)
        send_keys("{ENTER}")
        time.sleep(2.5)
        main_win = h.get_main_window()
    return payment_rows(main_win)


def payment_rows(main_win):
    grid = main_win.child_window(auto_id=PAYMENT_GRID, control_type="DataGrid")
    if not grid.exists(timeout=4):
        return []
    rows = []
    for row in grid.children(title="row", control_type="DataItem"):
        rows.append([(c.window_text() or "").strip() for c in row.children()])
    return rows


def complete_sale(main_win, timeout=30, attempts=3):
    """Finish the sale and PROVE it finished (the cart empties).

    A single Enter from the window is not enough: a run that had a valid
    credit payment line sitting in the grid pressed Enter, no print popup
    ever appeared, and the sale was silently left unpaid - cart still
    holding the item, no invoice in the database. The reliable route is
    the one pos_actions.do_payment_and_close already uses: put the focus
    in the Cash Amount field, Enter to confirm the amount, Enter again to
    raise the print prompt. Both Enters are re-sent on retry because the
    focus can land elsewhere after the reference popup closes."""
    for attempt in range(1, attempts + 1):
        main_win = h.get_main_window()
        cash_field = main_win.child_window(auto_id="textBoxCashAmount", control_type="Edit")
        if cash_field.exists(timeout=5):
            h.wait_and_click(cash_field, desc="Cash Amount field")
            time.sleep(0.6)
            send_keys("{ENTER}")
            time.sleep(2)

        main_win = h.get_main_window()
        main_win.set_focus()
        time.sleep(0.4)
        send_keys("{ENTER}")
        time.sleep(2.5)

        main_win = h.get_main_window()
        no_button = main_win.child_window(auto_id="SecondaryButton", control_type="Button")
        if no_button.exists(timeout=timeout):
            h.press_button_robust(no_button, desc="Print popup 'No' button")
            time.sleep(2)
            main_win = h.get_main_window()
            ok_button = main_win.child_window(auto_id="PrimaryButton", control_type="Button")
            if ok_button.exists(timeout=15):
                h.press_button_robust(ok_button, desc="Invoice created OK button")
                time.sleep(2)

        main_win = h.get_main_window()
        if len(cart_rows(main_win)) == 0:
            return main_win
        print("Sale does not look completed (cart still holds items), attempt %d/%d"
              % (attempt, attempts))

    raise AssertionError("the sale did not complete after %d attempts - the cart still holds items "
                         "and no invoice was generated" % attempts)


def sell_on_credit(main_win, mobile_no, barcode, reference="1"):
    """The whole credit sale: customer + item -> Payment Type Credit Sales
    -> amount -> reference -> pay. Returns a dict describing what happened
    so the test can assert on it and the report can show it."""
    main_win = open_sale_screen(main_win)
    add_customer_and_item(main_win, mobile_no, barcode)

    rows = cart_rows(main_win)
    total = grand_total(main_win)
    if not rows:
        raise AssertionError("item %s was not added to the cart" % barcode)

    select_credit_sales(main_win)
    pay_rows = add_credit_payment(main_win, total, reference=reference)
    if not pay_rows:
        raise AssertionError("the credit payment line was not added (reference popup not answered?)")

    main_win = complete_sale(main_win)
    return {
        "grand_total": total,
        "payment_rows": pay_rows,
        "cart_rows_after": len(cart_rows(main_win)),
    }


def exe_is_running():
    """The exe has been seen to disappear mid-flow; a test that then blames
    a missing window is confusing, so callers check this first."""
    try:
        h.get_main_window(timeout=3)
        return True
    except Exception:
        return False
