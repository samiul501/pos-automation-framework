# ============================================================
# WEB REPORT VERIFICATION - two checks against the backend web
# report (Customer Analysis / Invoice No Wise):
#
# 1. Every invoice sold TODAY (bulk view, no invoice number needed)
#    is checked for internal consistency - runs standalone, doesn't
#    need a fresh exe run.
# 2. Each transaction captured during the exe run (test_pos_full.py,
#    via config.WEB_VERIFY_DATA_FILE - see its test_07_close_app) is
#    looked up individually and compared against its exe-side
#    expected values. Skipped (not failed) if that file is missing
#    or empty, so check 1 above still runs on its own.
# ============================================================

import json
import os

import allure
import pytest
from allure_commons.types import Severity
from playwright.sync_api import sync_playwright

import config
import web_helpers as web_h

# Rows/footer amounts allow tiny float rounding slop (report values are
# rounded to 2 decimal places by the app; summed floats can be off by a
# fraction of a cent), but must never differ by a real cent or more.
_TOLERANCE = 0.01


def _to_float(value):
    return float(value.replace(",", ""))


def _check_internal_consistency(page, report, label, invoice_no, mismatches, index=None):
    """Beyond comparing the exe's GrandTotal against the web's Net Payable,
    verify the report is internally consistent - every item row summing to
    the Total row, and the footer summary matching the Total row - so a
    bug in one row or one footer field can't silently net out and slip
    through undetected. Any mismatch found is highlighted in red directly
    on the page, so it's visible in the screenshot attached afterward -
    not just described in the failure text.

    `index` is None for the single-invoice-lookup page (get_invoice_report),
    or the invoice's position on a bulk multi-invoice page
    (get_today_all_invoices_report) - the two need different highlighting
    helpers since a bulk page repeats the same labels once per invoice."""
    if index is None:
        highlight_total = web_h.highlight_total_row_field
        highlight_footer = web_h.highlight_footer_field
    else:
        highlight_total = lambda p, f: web_h.highlight_total_row_field_nth(p, f, index)
        highlight_footer = lambda p, l: web_h.highlight_footer_field_nth(p, l, index)

    total = report["total_row"]

    sums = {"gross_amount": 0.0, "discount": 0.0, "vat_amount": 0.0, "net_amount": 0.0, "net_payable": 0.0}
    for row in report["item_rows"]:
        for field in sums:
            sums[field] += _to_float(row[field])

    for field in sums:
        total_val = _to_float(total[field])
        if abs(sums[field] - total_val) > _TOLERANCE:
            mismatches.append(
                label + " (Invoice " + invoice_no + "): item rows' " + field + " sum to " +
                ("%.2f" % sums[field]) + " but Total row shows " + total[field]
            )
            highlight_total(page, field)

    footer = report["footer"]
    combined_discount = _to_float(footer["item_discount"]) + _to_float(footer["other_discount"])
    if abs(combined_discount - _to_float(total["discount"])) > _TOLERANCE:
        mismatches.append(
            label + " (Invoice " + invoice_no + "): footer Item Discount (" + footer["item_discount"] +
            ") + Other Discount (" + footer["other_discount"] + ") = " + ("%.2f" % combined_discount) +
            " but Total row Discount shows " + total["discount"]
        )
        highlight_footer(page, "Item Discount")
        highlight_footer(page, "Other Discount")
        highlight_total(page, "discount")

    if abs(_to_float(footer["gross_amount"]) - _to_float(total["gross_amount"])) > _TOLERANCE:
        mismatches.append(
            label + " (Invoice " + invoice_no + "): footer Gross Amount (" + footer["gross_amount"] +
            ") does not match Total row Gross Amount (" + total["gross_amount"] + ")"
        )
        highlight_footer(page, "Gross Amount")
        highlight_total(page, "gross_amount")

    if abs(_to_float(footer["vat_amount"]) - _to_float(total["vat_amount"])) > _TOLERANCE:
        mismatches.append(
            label + " (Invoice " + invoice_no + "): footer VAT Amount (" + footer["vat_amount"] +
            ") does not match Total row VAT Amount (" + total["vat_amount"] + ")"
        )
        highlight_footer(page, "VAT Amount")
        highlight_total(page, "vat_amount")

    # Confirmed live 2026-08-22: the footer's Grand Total (now labelled
    # "Grand Total (Inclusive)") was fixed to correctly equal Net Payable -
    # it used to double-count VAT (see memory/web_report_verification.md).
    # Still checked unconditionally (no exemption) so a regression back to
    # the old behavior shows up as a failure immediately, the same way the
    # exe's own known discount-switch bugs are left to fail rather than
    # special-cased into passing.
    net_payable = _to_float(total["net_payable"])
    grand_total = _to_float(footer["grand_total"])
    if abs(grand_total - net_payable) > _TOLERANCE:
        mismatches.append(
            label + " (Invoice " + invoice_no + "): footer Grand Total (" + footer["grand_total"] +
            ") should equal Net Payable (" + total["net_payable"] + ") but does not"
        )
        highlight_footer(page, "Grand Total")
        highlight_total(page, "net_payable")

    # CASH (what was actually tendered/received) should equal Net Payable
    # (what was actually owed) - found live 2026-08-22 by visually
    # scrolling through the bulk report, not by any automated check: one
    # invoice showed CASH 1,511.00 against a Net Payable of 1,510.50 - a
    # BDT 0.50 gap the earlier checks never looked for since they only
    # compared fields already known to be related (footer vs Total row).
    # Flagged unconditionally, same as everything else in this function -
    # no exemption for "it's probably just cash rounding", per the user's
    # explicit instruction to mark every mismatch found.
    cash = _to_float(footer["cash"])
    if abs(cash - net_payable) > _TOLERANCE:
        mismatches.append(
            label + " (Invoice " + invoice_no + "): CASH (" + footer["cash"] +
            ") does not match Net Payable (" + total["net_payable"] + ")"
        )
        highlight_footer(page, "CASH")
        highlight_total(page, "net_payable")


def _check_todays_bulk_report(page, mismatches):
    """Checks every invoice sold today in one pass - View clicked with a
    blank Invoice No (isDetails checked, From/To Date defaulting to
    today) - instead of only the specific invoices test_pos_full.py
    happened to capture. Requested by the user specifically so nothing
    sold today (from this run or any other activity) goes unchecked, not
    just the exe's own captured transactions. Runs BEFORE the per-invoice
    lookups below, as a broader first pass."""
    with allure.step("Checking every invoice sold today (bulk Customer Analysis view)"):
        invoices = web_h.get_today_all_invoices_report(page)
        for index, inv in enumerate(invoices):
            _check_internal_consistency(
                page, inv, "Today's bulk check", inv["invoice_no"], mismatches, index=index
            )
        allure.attach(
            page.screenshot(full_page=True),
            name="Today's invoices (" + str(len(invoices)) + " found)",
            attachment_type=allure.attachment_type.PNG
        )


# ---- one browser for the whole module ------------------------------
# The report page is opened ONCE and shared by every test below; each
# test is still its own Allure/PDF/mail line item, which is the point of
# splitting them: a mismatch in Transaction 4 no longer hides behind a
# single "13. Verify..." failure.

def _load_captured():
    if os.path.exists(config.WEB_VERIFY_DATA_FILE):
        with open(config.WEB_VERIFY_DATA_FILE) as f:
            return json.load(f)
    return []


# Loaded at import time because pytest needs the parametrize list when it
# collects the file - test_pos_full.py writes this file before this
# module is ever collected (they run as separate pytest sessions).
CAPTURED = _load_captured()


@pytest.fixture(scope="module")
def report_page():
    with sync_playwright() as p:
        # Headed on purpose - the user wants to watch this pass run
        # against the real web report.
        browser, page = web_h.open_customer_analysis_report(p, headless=False)
        try:
            yield page
        finally:
            browser.close()


# ---- test 1: every invoice sold today -------------------------------

@allure.feature("POS Full Flow")
@allure.story("Web Report Verification")
@allure.severity(Severity.CRITICAL)
def test_01_todays_invoices_internally_consistent(report_page):
    allure.dynamic.title("01. Checking every invoice sold today (bulk Customer Analysis view)")
    mismatches = []
    _check_todays_bulk_report(report_page, mismatches)
    assert not mismatches, "Today's bulk report has mismatches:\n" + "\n".join(mismatches)


# ---- test 2..n: one per captured exe transaction --------------------

def _entry_id(entry):
    return entry["label"] + " - " + entry["invoice_no"]


@allure.feature("POS Full Flow")
@allure.story("Web Report Verification")
@allure.severity(Severity.CRITICAL)
@pytest.mark.parametrize("entry", CAPTURED, ids=[_entry_id(e) for e in CAPTURED])
def test_02_transaction_landed_in_web_report(report_page, entry):
    # Plain serial: 1 is the bulk check above, transactions follow 2, 3, ...
    n = CAPTURED.index(entry) + 2
    # Zero-padded so Allure's name sort keeps 02..10 in order ("10." would
    # otherwise land right after "1.").
    allure.dynamic.title(
        "%02d. %s - Invoice %s (expected GrandTotal %s)"
        % (n, entry["label"], entry["invoice_no"], entry["expected_grand_total"])
    )
    page = report_page
    mismatches = []
    report = web_h.get_invoice_report(page, entry["invoice_no"])

    if report is None:
        allure.attach(page.screenshot(full_page=True),
                      name=entry["label"] + " - " + entry["invoice_no"] + " (NOT FOUND)",
                      attachment_type=allure.attachment_type.PNG)
        assert False, entry["label"] + " (Invoice " + entry["invoice_no"] + "): not found in web report"

    if entry["customer"] != report["customer_no"]:
        mismatches.append(
            entry["label"] + " (Invoice " + entry["invoice_no"] + "): customer mismatch - "
            "exe=" + entry["customer"] + " web=" + report["customer_no"]
        )
        web_h.highlight_customer_no(page)

    # Compared as floats, not strings - the exe's GrandTotal ("171") and
    # the web report's Net Payable ("171.00" / "1,590.00") are the same
    # amount in different formats. Net Payable is used deliberately, not
    # the footer's own "Grand Total" (see memory/web_report_verification.md).
    expected = _to_float(entry["expected_grand_total"])
    actual = _to_float(report["net_payable"])
    if abs(expected - actual) > _TOLERANCE:
        mismatches.append(
            entry["label"] + " (Invoice " + entry["invoice_no"] + "): GrandTotal mismatch - "
            "exe=" + entry["expected_grand_total"] + " web Net Payable=" + report["net_payable"]
        )
        web_h.highlight_total_row_field(page, "net_payable")

    _check_internal_consistency(page, report, entry["label"], entry["invoice_no"], mismatches)

    # Screenshot last, after mismatches have highlighted their fields in
    # red - the bad value is visible in the picture, not just the text.
    allure.attach(page.screenshot(full_page=True),
                  name=entry["label"] + " - " + entry["invoice_no"],
                  attachment_type=allure.attachment_type.PNG)

    assert not mismatches, entry["label"] + " has mismatches:\n" + "\n".join(mismatches)


if not CAPTURED:
    def test_02_no_captured_transactions_note():
        """Only exists when there was nothing to check - otherwise the
        transaction tests would just silently vanish from the report."""
        pytest.skip("no captured invoices from a recent exe run (" + config.WEB_VERIFY_DATA_FILE + " missing/empty)")
