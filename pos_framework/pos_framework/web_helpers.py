# ============================================================
# WEB HELPERS - generic Playwright utilities for the backend web
# report (demo-backoffice.example.com), used to verify that exe
# transactions land correctly in the Customer Analysis report.
# Mirrors pos_helpers.py's role for the desktop app: generic,
# reusable automation utilities only - comparison/assertion logic
# belongs in the test file, not here.
# ============================================================

import time

import config


def _settle(page, seconds=0):
    """Wait for the network to go quiet - but never fail if it does not.
    The backend keeps long-lived connections open (notifications), so
    "networkidle" intermittently never fires and a bare goto/
    wait_for_load_state raises a 30s timeout on a page that is in fact
    fully rendered - which left the login form unfilled (confirmed live
    2026-09-18). The fixed sleep is what the flow really relies on."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    if seconds:
        time.sleep(seconds)


def _goto(page, url, seconds=1.5):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        page.goto(url, timeout=45000)
    _settle(page, seconds)


def open_customer_analysis_report(playwright, headless=True):
    """Launch a fresh browser, log in, and navigate to POS > Reports >
    POS SALES REPORT > Customer Analysis. Returns (browser, page) so the
    caller can look up multiple invoices before closing the browser once.

    Uses a large fixed viewport (not just a maximized window) so
    screenshots capture every row and the full footer without cropping,
    regardless of headed/headless - no_viewport=True was tried and
    confirmed live to collapse the sidebar (and break navigation) under
    headless, since there is no real screen for "maximized" to size
    against there.

    The "View By" control is a react-select whose transparent overlay div
    intercepts plain clicks, so force=True is required on it and on the
    Customer Analysis option (confirmed live - see
    memory/web_report_verification.md)."""
    browser = playwright.chromium.launch(headless=headless, args=["--start-maximized"])
    if headless:
        # Fixed viewport under headless: there is no real screen for
        # "maximized" to size against, and no_viewport collapses the
        # sidebar there (confirmed live).
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
    else:
        # Headed: let the page fill the maximized window (true full-screen
        # view for the operator watching the verification).
        context = browser.new_context(no_viewport=True)
    page = context.new_page()
    _goto(page, config.WEB_BASE_URL)
    page.wait_for_selector("input[name='mobileNo']", timeout=30000)

    page.fill("input[name='mobileNo']", config.WEB_MOBILE)
    page.fill("input[name='password']", config.WEB_PASSWORD)
    page.click("button:has-text('LOG IN')")
    _settle(page, 3)

    # A site redeploy (confirmed live 2026-08-22) changed the sidebar to a
    # collapsed-by-default dropdown tree where "POS" -> "Reports" is no
    # longer directly clickable (a sibling <ul> intercepts the click even
    # though the link already exists in the DOM). Navigating straight to
    # the route sidesteps the sidebar entirely and is more robust anyway.
    _goto(page, config.WEB_BASE_URL.rstrip("/") + "/pos/reports", 1.5)
    page.click("text=POS SALES REPORT")
    time.sleep(1.5)

    page.click("text=Select View By", force=True)
    time.sleep(1)
    page.click("text=Customer Analysis", force=True)
    time.sleep(1.5)

    # Confirmed live: "isDetails" is unchecked by default on a fresh page
    # load - without it the report returns a summary instead of the
    # per-item/Total row breakdown get_invoice_report() below depends on.
    # .check() (not .click()) is idempotent, so repeat calls across
    # multiple invoice searches in the same session won't accidentally
    # toggle it back off.
    page.locator("input[name='isDetails']").check(force=True)
    time.sleep(0.5)

    return browser, page


def _row_to_dict(cells):
    """Maps one item/Total table row's cells to named fields. Column order
    confirmed live: SL, Barcode, Item Name, Quantity, Selling Price, Gross
    Amount, Discount, VAT Amount, Net Amount, Net Payable, COGS."""
    return {
        "sl": cells[0].strip(),
        "barcode": cells[1].strip(),
        "item_name": cells[2].strip(),
        "quantity": cells[3].strip(),
        "selling_price": cells[4].strip(),
        "gross_amount": cells[5].strip(),
        "discount": cells[6].strip(),
        "vat_amount": cells[7].strip(),
        "net_amount": cells[8].strip(),
        "net_payable": cells[9].strip(),
        "cogs": cells[10].strip(),
    }


def _footer_value(page, label):
    """The footer's summary lines (e.g. "Item Discount: 10.00") share their
    label text with the table's own column headers (e.g. "Gross Amount",
    "VAT Amount"), so `.first` can match the header instead of the footer.
    `.last` is the confirmed-live reliable way to reach the footer line.

    The matched element's own inner_text() is just the label ("Gross
    Amount: ") - the number itself lives in a sibling element, so the
    parent element's innerText (label + value together) has to be read
    instead (confirmed live)."""
    element = page.locator("text=" + label).last
    text = element.evaluate("el => el.parentElement.innerText")
    return text.split(":", 1)[1].strip()


def get_invoice_report(page, invoice_no):
    """Search a single invoice number in the already-open Customer
    Analysis report and return every row plus the footer summary, or None
    if the invoice isn't found ("No Data Found"). Returns everything
    visible on the page (not just the Total row) so the caller can check
    internal consistency (item rows summing to the Total row, footer
    matching the Total row) in addition to comparing against the exe -
    this is deliberate: checking only one aggregate number could miss a
    bug that happens to net out at the total.

    Net Payable (on the Total row) is the authoritative total to compare
    against the exe's own GrandTotal. The footer's "Grand Total" line
    used to double-count VAT (a confirmed app bug - see
    memory/web_report_verification.md); confirmed live 2026-08-22 that a
    site update fixed this - it's now labelled "Grand Total (Inclusive)"
    and correctly equals Net Payable. Kept as a separate field from
    Net Payable anyway in case a future deploy regresses it."""
    invoice_input = page.locator("input[placeholder='Invoice No']")
    invoice_input.fill("")
    invoice_input.fill(invoice_no)
    time.sleep(0.5)
    page.click("button:has-text('View')", force=True)
    _settle(page)
    time.sleep(2)

    if page.locator("text=No Data Found").count() > 0:
        return None

    customer_line = page.locator("text=Customer:").first.inner_text()
    customer = customer_line.split(":", 1)[1].strip()

    # "Customer No:" (the phone number) is the reliable match key against the
    # exe side, which only knows customers by phone number - the "Customer:"
    # name label above is for display/reading, not comparison.
    customer_no_line = page.locator("text=Customer No:").first.inner_text()
    customer_no = customer_no_line.split(":", 1)[1].strip()

    rows = page.locator("table tbody tr")
    row_count = rows.count()
    item_rows = [_row_to_dict(rows.nth(i).locator("td").all_inner_texts()) for i in range(row_count - 1)]

    total_cells = rows.nth(row_count - 1).locator("td").all_inner_texts()
    # Total row shape differs slightly from item rows (no Barcode/Item
    # Name/Selling Price columns): ["Total:", Qty, "", Gross, Discount,
    # VAT, Net Amount, Net Payable, COGS].
    total_row = {
        "quantity": total_cells[1].strip(),
        "gross_amount": total_cells[3].strip(),
        "discount": total_cells[4].strip(),
        "vat_amount": total_cells[5].strip(),
        "net_amount": total_cells[6].strip(),
        "net_payable": total_cells[7].strip(),
        "cogs": total_cells[8].strip(),
    }

    footer = {
        "gross_amount": _footer_value(page, "Gross Amount"),
        "vat_amount": _footer_value(page, "VAT Amount"),
        "item_discount": _footer_value(page, "Item Discount"),
        "other_discount": _footer_value(page, "Other Discount"),
        "grand_total": _footer_value(page, "Grand Total"),
        "cash": _footer_value(page, "CASH"),
    }

    return {
        "customer": customer,
        "customer_no": customer_no,
        "item_rows": item_rows,
        "total_row": total_row,
        "footer": footer,
        # Kept for convenience/back-compat with simple total-only checks.
        "net_payable": total_row["net_payable"],
    }


# Total row cell index by field name (0="Total:", 2="" are unused - the
# Total row has no Barcode/Item Name/Selling Price columns).
_TOTAL_ROW_COLUMN_INDEX = {
    "quantity": 1, "gross_amount": 3, "discount": 4,
    "vat_amount": 5, "net_amount": 6, "net_payable": 7, "cogs": 8,
}


def _highlight(locator):
    """Draws a visible red highlight box around an element so a mismatch
    is obvious directly in the screenshot, not just in the failure text."""
    locator.evaluate(
        "el => { el.style.outline = '4px solid red'; "
        "el.style.backgroundColor = '#ffcccc'; }"
    )


def highlight_footer_field(page, label):
    """Highlights a footer summary line (e.g. "Item Discount: 10.00") by
    label - highlights the label+value together since the value lives in
    a sibling element, not the label's own node (see _footer_value)."""
    element = page.locator("text=" + label).last
    _highlight(element.locator("xpath=.."))


def highlight_total_row_field(page, field_name):
    """Highlights the Total row's cell for the given field name."""
    rows = page.locator("table tbody tr")
    total_row = rows.nth(rows.count() - 1)
    _highlight(total_row.locator("td").nth(_TOTAL_ROW_COLUMN_INDEX[field_name]))


def highlight_customer_no(page):
    """Highlights the "Customer No:" line."""
    element = page.locator("text=Customer No:").first
    _highlight(element.locator("xpath=.."))


def _nearest_by_y(anchor_y, locators, tolerance=40):
    """Matches a locator collection to a Y-coordinate by closest vertical
    position (within `tolerance` px) - used because "Customer:"/"Customer
    No:" aren't guaranteed one-per-invoice (a blank-customer sale has
    neither line at all, confirmed live 2026-08-22), unlike every other
    per-invoice label, so simple index pairing can silently misattribute
    one invoice's customer to another. Returns "" if nothing is close
    enough to count as belonging to this invoice."""
    best_text, best_diff = "", tolerance
    for i in range(locators.count()):
        box = locators.nth(i).bounding_box()
        if not box:
            continue
        diff = abs(box["y"] - anchor_y)
        if diff < best_diff:
            best_diff = diff
            best_text = locators.nth(i).inner_text().split(":", 1)[1].strip()
    return best_text


def get_today_all_invoices_report(page):
    """Clicks View with a blank Invoice No (isDetails already checked by
    open_customer_analysis_report) - the "Based From/To Date" fields
    default to today, so this returns every invoice sold today in one
    pass, without needing to already know their invoice numbers.

    Confirmed live (2026-08-22) that with N invoices shown, the page
    repeats N times, strictly in the same top-to-bottom order, for:
    "Invoice No:" (1 each), <table> (1 each), and the footer's "Item
    Discount"/"Other Discount"/"Grand Total (Inclusive)" (1 each) - but
    "Gross Amount"/"VAT Amount" appear TWICE per invoice (once as a table
    column header, once in the footer), so the footer occurrence is
    always the odd index (2*i + 1). "Customer:"/"Customer No:" are the
    one exception - a blank-customer sale has neither line at all, so
    those are matched by Y-position instead of by index (see
    _nearest_by_y). Returns a list of dicts shaped like
    get_invoice_report()'s return value, in the same order as they
    appear on the page."""
    page.locator("input[placeholder='Invoice No']").fill("")
    page.click("button:has-text('View')", force=True)
    _settle(page)

    # A fixed sleep here was confirmed live to flake on a cold browser
    # (the very first View click after login can render slower than a
    # fixed 2s wait) - wait for either result to actually appear instead.
    try:
        page.locator("table, text=No Data Found").first.wait_for(state="visible", timeout=15000)
    except Exception:
        pass
    time.sleep(1)

    if page.locator("text=No Data Found").count() > 0:
        return []

    invoice_no_locs = page.locator("text=Invoice No:")
    customer_locs = page.locator("text=Customer:")
    customer_no_locs = page.locator("text=Customer No:")
    tables = page.locator("table")
    gross_locs = page.locator("text=Gross Amount")
    vat_locs = page.locator("text=VAT Amount")
    item_disc_locs = page.locator("text=Item Discount")
    other_disc_locs = page.locator("text=Other Discount")
    grand_total_locs = page.locator("text=Grand Total")
    cash_locs = page.locator("text=CASH")

    count = invoice_no_locs.count()
    # If this ever fails, the page structure changed again and the index
    # arithmetic below can no longer be trusted - fail loudly instead of
    # silently pairing up the wrong invoice's rows/footer. Customer/
    # Customer No are deliberately NOT asserted here - see _nearest_by_y.
    assert tables.count() == count, "table count does not match invoice count - page structure may have changed"
    assert item_disc_locs.count() == count, "Item Discount count does not match invoice count"
    assert other_disc_locs.count() == count, "Other Discount count does not match invoice count"
    assert grand_total_locs.count() == count, "Grand Total count does not match invoice count"
    assert cash_locs.count() == count, "CASH count does not match invoice count"
    assert gross_locs.count() == count * 2, "Gross Amount count is not exactly double the invoice count"
    assert vat_locs.count() == count * 2, "VAT Amount count is not exactly double the invoice count"

    invoices = []
    for i in range(count):
        invoice_no_loc = invoice_no_locs.nth(i)
        invoice_no = invoice_no_loc.inner_text().split(":", 1)[1].strip()
        anchor_box = invoice_no_loc.bounding_box()
        anchor_y = anchor_box["y"] if anchor_box else None
        customer = _nearest_by_y(anchor_y, customer_locs) if anchor_y is not None else ""
        customer_no = _nearest_by_y(anchor_y, customer_no_locs) if anchor_y is not None else ""

        rows = tables.nth(i).locator("tbody tr")
        row_count = rows.count()
        item_rows = [_row_to_dict(rows.nth(r).locator("td").all_inner_texts()) for r in range(row_count - 1)]
        total_cells = rows.nth(row_count - 1).locator("td").all_inner_texts()
        total_row = {
            "quantity": total_cells[1].strip(),
            "gross_amount": total_cells[3].strip(),
            "discount": total_cells[4].strip(),
            "vat_amount": total_cells[5].strip(),
            "net_amount": total_cells[6].strip(),
            "net_payable": total_cells[7].strip(),
            "cogs": total_cells[8].strip(),
        }

        def footer_text(loc):
            return loc.evaluate("el => el.parentElement.innerText").split(":", 1)[1].strip()

        footer = {
            "gross_amount": footer_text(gross_locs.nth(2 * i + 1)),
            "vat_amount": footer_text(vat_locs.nth(2 * i + 1)),
            "item_discount": footer_text(item_disc_locs.nth(i)),
            "other_discount": footer_text(other_disc_locs.nth(i)),
            "grand_total": footer_text(grand_total_locs.nth(i)),
            "cash": footer_text(cash_locs.nth(i)),
        }

        invoices.append({
            "invoice_no": invoice_no,
            "customer": customer,
            "customer_no": customer_no,
            "item_rows": item_rows,
            "total_row": total_row,
            "footer": footer,
            "net_payable": total_row["net_payable"],
        })

    return invoices


def highlight_total_row_field_nth(page, field_name, index):
    """Same as highlight_total_row_field() but for the index-th invoice
    table on a page showing multiple invoices at once (bulk view)."""
    total_row = page.locator("table").nth(index).locator("tbody tr").last
    _highlight(total_row.locator("td").nth(_TOTAL_ROW_COLUMN_INDEX[field_name]))


def highlight_footer_field_nth(page, label, index):
    """Same as highlight_footer_field() but for the index-th invoice's
    footer block on a bulk (multi-invoice) page. "Gross Amount"/"VAT
    Amount" occur twice per invoice (header + footer), so the footer
    occurrence is the odd index (2*index + 1); other footer labels occur
    once per invoice, so it's just `index`."""
    nth = 2 * index + 1 if label in ("Gross Amount", "VAT Amount") else index
    element = page.locator("text=" + label).nth(nth)
    _highlight(element.locator("xpath=.."))


def highlight_customer_no_nth(page, index):
    """Same as highlight_customer_no() but for the index-th invoice on a
    bulk (multi-invoice) page."""
    element = page.locator("text=Customer No:").nth(index)
    _highlight(element.locator("xpath=.."))
