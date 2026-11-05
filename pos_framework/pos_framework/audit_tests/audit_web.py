# ============================================================
# AUDIT WEB - Playwright automation for the two backend screens
# the audit flow needs: Inventory > Audit Setup (create the
# scope) and the approval screen that releases it to the exe.
#
# Mirrors web_helpers.py's role - generic navigation/interaction
# only. Assertions belong in the test files.
#
# SELECTORS: WHY THESE AND NOT NAMES
# ----------------------------------
# The form's dropdowns are react-selects. Only Category and Sub
# Category carry a named hidden input (name='category' /
# 'subCategory'); Office, Warehouse and - crucially - the new
# Supplier control have NO name attribute at all, so
# fill("[name=...]") cannot reach them. What every one of them
# DOES have is a stable id on its react-select container:
#
#   #office  #warehouse  #supplier  #category  #subCategory
#
# so this module drives them by container id. Verified live
# 2026-09-15 by dumping the form's DOM.
#
# TWO ORDERING RULES, both confirmed live and both silent if
# broken:
#   1. #warehouse does not exist in the DOM until an Office is
#      chosen. Selecting warehouse first simply finds nothing.
#   2. #supplier is an async search box ("Select/Search
#      Supplier"), not a plain list - its options only appear
#      after typing, and the FIRST search after opening often
#      returns an empty list while the request is still in
#      flight. _pick_searchable retries rather than concluding
#      "no such supplier".
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

from audit_tests import audit_config as acfg

_OPTION_SELECTOR = "div[class*='-option']"


# ---- session -------------------------------------------------------

def login(playwright, headless=True):
    """Fresh browser logged into the backend. Returns (browser, page).

    Same fixed 1920x1080 viewport as web_helpers uses, for the same
    reason: no_viewport collapses the sidebar under headless and breaks
    navigation, and a large viewport keeps full-page screenshots
    uncropped."""
    browser = playwright.chromium.launch(headless=headless, args=["--start-maximized"])
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()
    _goto(page, config.WEB_BASE_URL)
    page.fill("input[name='mobileNo']", config.WEB_MOBILE)
    page.fill("input[name='password']", config.WEB_PASSWORD)
    page.click("button:has-text('LOG IN')")
    _settle(page, 3)
    return browser, page


def _settle(page, seconds):
    """Wait for the network to go quiet, but never fail because it
    didn't.

    This app keeps long-lived connections open (notifications), so
    "networkidle" intermittently never fires and a bare
    wait_for_load_state() raises a 30s timeout on a page that is in fact
    fully rendered - it took down a report run mid-way. The fixed sleep
    afterwards is what the rest of the suite actually relies on."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(seconds)


def _goto(page, url, seconds=2):
    """Navigate without letting a never-idle page abort the run."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        page.goto(url, timeout=45000)
    _settle(page, seconds)


def _url(route):
    return config.WEB_BASE_URL.rstrip("/") + route


# ---- react-select helpers ------------------------------------------

def _visible_options(page):
    return [
        t.strip()
        for t in page.eval_on_selector_all(
            _OPTION_SELECTOR, "els => els.map(e => (e.innerText || '').trim())"
        )
        if t.strip()
    ]


def _pick(page, container_id, option_text, timeout=15, attempts=4):
    """Open a plain react-select by container id and click one option.

    WAITS FOR THE LIST TO POPULATE: these selects refetch their options
    whenever a field above them changes (the report's Audit list reloads
    after Office, and again after each View), so a click that lands while
    the list is still empty raised "not found among 0 options" - which
    happened on the second supplier's report, after the first one had
    worked. Reopening and waiting is what makes it dependable.

    force=True throughout: the controls render a transparent overlay div
    that intercepts ordinary clicks (same as web_helpers' View By)."""
    page.wait_for_selector("#" + container_id, timeout=timeout * 1000)
    for attempt in range(1, attempts + 1):
        page.click("#" + container_id, force=True)
        # give the options a moment to arrive, a little longer each retry
        deadline = time.time() + 2.5 * attempt
        options = []
        while time.time() < deadline:
            options = _visible_options(page)
            if options:
                break
            time.sleep(0.3)
        if options:
            try:
                _click_option(page, option_text)
                time.sleep(1.0)
                return
            except AssertionError:
                if attempt == attempts:
                    raise
        if attempt == attempts:
            raise AssertionError("#%s offered no options for %r after %d attempts"
                                 % (container_id, option_text, attempts))
        page.keyboard.press("Escape")
        time.sleep(1.2)


def _click_option(page, text):
    """Click the option whose text is EXACTLY `text`, falling back to a
    substring match only when no exact one exists.

    has_text alone is a substring match, and that bit hard: asking for
    sub-category "COSMETICS#" picked "COLOR COSMETICS#" (the first row
    containing it), the audit scope was saved with the wrong
    sub-category, and every in-scope item was then rightly refused by
    the exe as "Not Found" - a whole run misread as an app bug."""
    options = page.locator(_OPTION_SELECTOR)
    n = options.count()
    for i in range(n):
        if options.nth(i).inner_text().strip() == text:
            options.nth(i).click(force=True)
            return True
    fallback = page.locator(_OPTION_SELECTOR, has_text=text)
    if fallback.count():
        fallback.first.click(force=True)
        return True
    raise AssertionError("option %r not found among %d options" % (text, n))


def _pick_searchable(page, container_id, search_text, option_text=None,
                     attempts=3):
    """Open an async-search react-select, type, and click the match.

    Retries the typing: the first search after opening the control
    regularly comes back with zero options because the request has not
    landed yet (confirmed live - searching "Audit" returned [] while the
    very next search for "American" returned three rows). Without the
    retry that reads as "the supplier does not exist"."""
    want = option_text or search_text
    page.wait_for_selector("#" + container_id, timeout=15000)

    for attempt in range(1, attempts + 1):
        page.click("#" + container_id, force=True)
        time.sleep(0.8)
        # Clear whatever a previous attempt typed.
        for _ in range(len(search_text) + 4):
            page.keyboard.press("Backspace")
        page.keyboard.type(search_text, delay=110)
        time.sleep(2.5 * attempt)          # widen the wait each retry

        options = _visible_options(page)
        if want in options or page.locator(_OPTION_SELECTOR, has_text=want).count() > 0:
            _click_option(page, want)
            time.sleep(1.0)
            return True
        if attempt == attempts:
            raise AssertionError(
                "no option matching %r in #%s after %d attempts; last options seen: %r"
                % (want, container_id, attempts, options)
            )
        page.keyboard.press("Escape")
        time.sleep(0.8)
    return False


def selected_text(page, container_id):
    """What a dropdown currently displays - for asserting a pick landed
    instead of trusting that the click did something."""
    return page.locator("#" + container_id).inner_text().strip()


# ---- Audit Setup: create -------------------------------------------

def open_create_audit(page):
    """Inventory > Audit Setup > Create.

    Navigates by route, not by sidebar: the sidebar is a
    collapsed-by-default tree whose sibling <ul> intercepts clicks (see
    web_helpers). /inventory/auditSetup is the list screen and
    /inventory/auditSetup/create the form - both confirmed live."""
    _goto(page, _url("/inventory/auditSetup/create"), 3)
    page.wait_for_selector("text=Create Audit", timeout=20000)


def fill_audit_header(page, office_name, warehouse_name, start_date,
                      closing_date, description):
    """The header half of the form. Office MUST be set before warehouse
    - #warehouse is not in the DOM until then."""
    _pick(page, "office", office_name)
    _pick(page, "warehouse", warehouse_name)
    page.fill("input[name='startDate']", start_date)
    page.fill("input[name='closingDate']", closing_date)
    page.fill("input[name='remarks']", description)
    time.sleep(0.5)


def add_scope_row(page, supplier_search, category_name, sub_category_name=None,
                  supplier_option=None, category_option=None):
    """Add one (supplier, category, sub category) scope row and verify
    it landed in the grid.

    Pass supplier_search="All" for All Suppliers.

    SUB CATEGORY IS EFFECTIVELY REQUIRED (confirmed live 2026-09-16): the
    spec lists it as optional ("All Sub Categories"), but clicking Add
    with it blank raises the toast "Please select a sub-category." and
    stages nothing. Callers must always pass one.

    Supplier names are not unique prefixes - searching "American" offers
    both "American Chef (Ornate Services Limited)" and "American Suplier
    Ajmol" - so supplier_option names the exact row to click.

    The grid is checked after Add because a rejected Add is silent apart
    from a toast - without this check a later SAVE fails with a bare
    HTTP 400 (the server rejects duplicate rows) and nothing says why."""
    before = len(scope_grid_rows(page))
    _pick_searchable(page, "supplier", supplier_search, supplier_option)
    _pick(page, "category", category_option or category_name)
    if sub_category_name:
        _pick(page, "subCategory", sub_category_name)
    page.click("button:has-text('Add')", force=True)
    time.sleep(1.5)
    rows = scope_grid_rows(page)
    toasts = toast_messages(page)
    if len(rows) != before + 1:
        raise AssertionError("scope row was not added (%s + %s / %s): toasts=%s"
                             % (supplier_option or supplier_search, category_name,
                                sub_category_name, toasts))
    want_sup = supplier_option or supplier_search
    # The grid may list newest-first, so look for the row rather than
    # assume a position.
    match = [r for r in rows if r["category"] == category_name
             and (want_sup.lower() == "all" or r["supplier"] == want_sup)]
    if not match:
        raise AssertionError("no staged row for %r + %r; grid=%s" % (want_sup, category_name, rows))
    return match[-1]


def scope_grid_rows(page):
    """The scope rows currently staged in the grid, read back from the
    table. Columns are SL | Supplier Name | Category Code | Category
    Name | Sub Category Name | Action.

    Reading these back is what proves the Supplier column is actually
    populated in the UI - the spec's new column is invisible in the DB
    until Save, so the grid is the only pre-save evidence."""
    return page.evaluate(
        """() => {
            const rows = [];
            document.querySelectorAll('table tbody tr').forEach(tr => {
                const c = Array.from(tr.querySelectorAll('td'))
                               .map(td => (td.innerText || '').trim());
                if (c.length >= 5) {
                    rows.push({sl: c[0], supplier: c[1], categoryCode: c[2],
                               category: c[3], subCategory: c[4]});
                }
            });
            return rows;
        }"""
    )


def save_audit(page):
    """Click SAVE and wait for the form to settle. Returns the page URL
    afterwards - the app navigates back to the list on success, so a URL
    still ending in /create is the first sign the save was rejected."""
    page.click("button:has-text('SAVE')", force=True)
    _settle(page, 4)
    return page.url


def toast_messages(page):
    """Any toast/alert text currently on screen - the app reports both
    validation refusals (e.g. a duplicate scope row) and success this
    way, and a test needs to tell those apart."""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll(
              "[class*='toast'],[class*='Toast'],[role='alert'],[class*='snackbar'],[class*='Snackbar']"
           )).map(e => (e.innerText || '').trim()).filter(t => t)"""
    )


# ---- Audit Setup: list / approval ----------------------------------

def open_audit_setup_list(page):
    _goto(page, _url("/inventory/auditSetup"), 3)


def open_approval(page):
    """The common approval screen. The sidebar exposes exactly one
    approval entry that covers inventory - /commonapproval (there is
    also /centralapproval and an HR-only /hrAdmin/pendingApproval,
    neither of which is this flow). It renders a grid of approval cards
    grouped under ALL-CAPS headings; INVENTORY APPROVAL is the one that
    holds "Audit Config Approval"."""
    _goto(page, _url("/commonapproval"), 3.5)


def open_audit_config_approval(page):
    """Approval > Inventory > Audit Config Approval.

    The card on /commonapproval is a div with a click handler, not an
    anchor, so it cannot be reached by href - but clicking it lands on
    /commonapproval/auditconfigapproval, which this navigates to
    directly. Note the neighbouring card is "Audit Approval", a
    different queue (the audit results, not the config).

    Columns: (checkbox) | SL | Code | Audit Description | Office Name |
    Warehouse | Status | Action."""
    _goto(page, _url("/commonapproval/auditconfigapproval"), 4)


def approval_queue_rows(page):
    """Rows currently in the audit-config approval queue."""
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('table tbody tr').forEach(tr => {
                const c = Array.from(tr.querySelectorAll('td'))
                               .map(td => (td.innerText || '').trim());
                if (c.length >= 7) {
                    out.push({sl: c[1], code: c[2], description: c[3],
                              office: c[4], warehouse: c[5], status: c[6]});
                }
            });
            return out;
        }"""
    )


def approve_audit_setup(page, code, timeout=20):
    """Approve ONE audit setup by its code.

    Three things here are not obvious and each one silently does nothing
    if got wrong (all confirmed live 2026-09-15):

    1. The row checkbox is a React controlled input. Playwright's
       .check() sets the DOM property without firing the change React
       listens for - the box appears ticked and the page never notices.
       A real .click() is required.
    2. The Approve button starts DISABLED and only enables once a row is
       selected, so clicking it first is a no-op with no error.
    3. Approving raises a confirmation modal ("Are you sure you want to
       Approve?  NO / YES"). Without the YES click the request is never
       sent - which is exactly how a run can report success while the
       setup stays Pending.

    Only the row's own checkbox is touched, never the header
    select-all - that would approve every queued audit, including other
    people's.
    """
    row = page.locator("tr", has_text=code).first
    row.wait_for(timeout=timeout * 1000)

    checkbox = row.locator("input[type='checkbox']").first
    checkbox.click(force=True)          # NOT .check() - see docstring
    time.sleep(1.2)

    button = page.locator("button:has-text('Approve')").first
    if not button.is_enabled():
        raise AssertionError(
            "Approve is still disabled after selecting row %s - the checkbox "
            "click did not register" % code
        )
    button.click(force=True)
    time.sleep(2)

    _confirm_modal(page, "YES")
    _settle(page, 3)


def reject_audit_setup(page, code, timeout=20):
    """Reject one audit setup - same mechanics as approve."""
    row = page.locator("tr", has_text=code).first
    row.wait_for(timeout=timeout * 1000)
    row.locator("input[type='checkbox']").first.click(force=True)
    time.sleep(1.2)
    page.locator("button:has-text('Reject')").first.click(force=True)
    time.sleep(2)
    _confirm_modal(page, "YES")
    _settle(page, 3)


def _confirm_modal(page, button_text):
    """Click through the "Are you sure...?" modal if one appeared.

    The modal's text is duplicated in the DOM (two matching containers),
    so this targets the button rather than counting containers."""
    selector = (
        "div[class*='modal'] button:has-text('%s'), "
        "div[role='dialog'] button:has-text('%s'), "
        "div[class*='swal'] button:has-text('%s')"
        % (button_text, button_text, button_text)
    )
    button = page.locator(selector)
    if button.count():
        button.first.click(force=True)
        time.sleep(2.5)
        return True
    return False


def screenshot(page, path, full_page=True):
    page.screenshot(path=path, full_page=full_page)
    return path


# ---- Audit Summary Report ------------------------------------------
# POS > Reports > INVENTORY REPORT tab > View By = "Audit Summary
# Report". Controls, by react-select container id (mapped live):
#   #office   #audit   #basedOn (Item/Supplier/Category/Sub Category/
#   Minor Category)   #supplier (appears ONLY after basedOn=Supplier)
#   #basedOn2 (All Items/With Stock/Without Stock)
#   #filterBy (Counted Items/Uncounted Items/Short/Excess)
#   input[name=isDetails]   button "View"
#
# Every one of #basedOn, #basedOn2, #filterBy AND the supplier picker
# must be set: with any of them empty the View button fires NO request
# at all and the page just keeps saying "No Data Found" - which looks
# exactly like an empty audit. Confirmed by watching the network.

REPORT_OFFICE_NAME = "Dhanmondi Outlet"      # OfficeId 9 = audit_config.AUDIT_OFFICE_ID


def open_audit_summary_report(page):
    _goto(page, _url("/pos/reports"), 4)
    page.locator("text=INVENTORY REPORT").first.click(force=True)
    _settle(page, 3)
    _pick(page, "viewBy", "Audit Summary Report")
    _settle(page, 4)


def run_audit_summary(page, audit_code, based_on="Supplier", supplier_name=None,
                      office_name=REPORT_OFFICE_NAME, based_on2="All Items",
                      filter_by="Counted Items", details=True):
    """Fill the filters and click View. Returns the parsed report:
    {'columns': [...], 'rows': [{...}], 'total': {...} | None,
     'no_data': bool}.

    supplier_name is required when based_on == "Supplier" ("All" is a
    valid value and lists every supplier)."""
    _pick(page, "office", office_name)
    _settle(page, 3)
    # The audit list reloads asynchronously after the office pick; a
    # click that lands before the reload selects nothing (hidden input
    # stays '') and the report silently returns "No Data Found". Verify
    # the hidden value and retry instead.
    for attempt in range(4):
        _pick(page, "audit", audit_code)
        time.sleep(1.5)
        if _hidden_value(page, "audit"):
            break
        time.sleep(2)
    else:
        raise AssertionError("audit %r never registered in the report filter" % audit_code)
    _pick(page, "basedOn", based_on)
    time.sleep(1.5)
    if based_on == "Supplier":
        if not supplier_name:
            raise ValueError("supplier_name is required when based_on='Supplier'")
        page.wait_for_selector("#supplier", timeout=15000)
        if supplier_name.strip().lower() == "all":
            _pick(page, "supplier", "All")
        else:
            _pick_searchable(page, "supplier", supplier_name, supplier_name)
        time.sleep(1)
    _pick(page, "basedOn2", based_on2)
    time.sleep(0.8)
    _pick(page, "filterBy", filter_by)
    time.sleep(0.8)
    checkbox = page.locator("input[name='isDetails']")
    if checkbox.count() and checkbox.first.is_checked() != details:
        checkbox.first.click(force=True)
        time.sleep(0.5)

    page.locator("button:has-text('View')").last.click(force=True)
    _settle(page, 8)
    return parse_audit_summary(page)


# Column layout of the detailed Audit Summary Report (two header rows;
# the first groups System / Audit / Short / Excess / Difference, each
# with Quantity, Cost Amount, Sale Amount).
_REPORT_COLUMNS = [
    "sl", "barcode", "item", "category", "sub_category", "minor_category",
    "supplier", "avg_cost", "sale_price",
    "system_qty", "system_cost", "system_sale",
    "audit_qty", "audit_cost", "audit_sale",
    "short_qty", "short_cost", "short_sale",
    "excess_qty", "excess_cost", "excess_sale",
    "diff_qty", "diff_cost", "diff_sale",
]
_TOTAL_COLUMNS = _REPORT_COLUMNS[9:]     # the Total row starts at system_qty


def _num(text):
    t = (text or "").replace(",", "").strip()
    if t in ("", "-"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return text


def _hidden_value(page, name):
    loc = page.locator("input[type='hidden'][name='%s']" % name)
    return loc.first.input_value() if loc.count() else ""


def parse_audit_summary(page):
    no_data = page.locator("text=No Data Found").count() > 0 and \
        page.locator("text=No Data Found").first.is_visible()
    raw = page.evaluate(
        """() => { const o = [];
             document.querySelectorAll('table tr').forEach(tr => {
               const c = Array.from(tr.querySelectorAll('td,th'))
                              .map(td => (td.innerText || '').trim());
               if (c.length) o.push(c); });
             return o; }"""
    )
    rows, total = [], None
    for cells in raw:
        if not cells:
            continue
        if cells[0] == "Total":
            vals = [_num(c) for c in cells[1:]]
            total = dict(zip(_TOTAL_COLUMNS, vals))
        elif cells[0].isdigit() and len(cells) >= len(_REPORT_COLUMNS):
            row = dict(zip(_REPORT_COLUMNS, cells))
            for k in _REPORT_COLUMNS[7:]:
                row[k] = _num(row[k])
            rows.append(row)
    return {"columns": _REPORT_COLUMNS, "rows": rows, "total": total, "no_data": no_data}


# ---- same-session navigation (sidebar) ------------------------------
# The operator's flow is ONE login: build data, set up the audit, approve,
# scan on the exe, read the report - all in the same maximized browser.
# These openers navigate through the sidebar so the app keeps its
# menu/feature context (direct URLs lost it on the supplier form), with
# the route as a fallback.

def _sidebar(page, groups, href, settle=4):
    from audit_tests import audit_env as aenv
    try:
        return aenv.sidebar_goto(page, groups, href, settle=settle)
    except Exception:
        _goto(page, _url(href), settle)
        return page.url


def open_create_audit_in_session(page):
    """Inventory > Audit Setup > Create, on the current session."""
    _sidebar(page, ["Inventory"], "/inventory/auditSetup")
    page.locator("button:has-text('Create')").first.click(force=True)
    _settle(page, 4)
    page.wait_for_selector("text=Create Audit", timeout=20000)


def open_audit_config_approval_in_session(page):
    """Approval > (INVENTORY APPROVAL) Audit Config Approval, on the
    current session - clicks the card rather than jumping to its URL."""
    try:
        page.locator(".sbv2-label", has_text="Approval").first.click(force=True)
        _settle(page, 3.5)
        page.locator("text=Audit Config Approval").last.click(force=True)
        _settle(page, 4)
    except Exception:
        _goto(page, _url("/commonapproval/auditconfigapproval"), 4)
    page.wait_for_selector("table", timeout=20000)


def open_audit_summary_report_in_session(page):
    """POS > Reports > INVENTORY REPORT > Audit Summary Report, on the
    current session."""
    _sidebar(page, ["POS"], "/pos/reports")
    page.locator("text=INVENTORY REPORT").first.click(force=True)
    _settle(page, 3)
    _pick(page, "viewBy", "Audit Summary Report")
    _settle(page, 4)
