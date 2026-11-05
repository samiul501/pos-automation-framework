# ============================================================
# REPORTER - turns one finished run into a self-contained PDF:
# verdict, summary, EVERY test with its pass/fail status, failure
# reasons, sign-off. Rendered with the Playwright Chromium the
# framework already ships, so no extra PDF library is needed.
#
# The PDF exists because the Allure report lives on this machine
# only - recipients of the mail cannot open it, so the evidence has
# to travel with the mail.
# ============================================================

import datetime
import os
import re

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(DASHBOARD_DIR, "reports")

AUTHOR = "Samiul Islam"
AUTHOR_TITLE = "Junior SQA"


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_duration(seconds):
    seconds = int(seconds or 0)
    return "%dm %02ds" % (seconds // 60, seconds % 60)


def _pretty_test_name(name):
    """test_02d_underpay_then_correct_sale -> '02d · Underpay then correct sale'.
    An Allure title ("03. Transaction 2 - Invoice ...") is shown verbatim."""
    if not name.startswith("test_"):
        return name
    n = re.sub(r"^test_", "", name)
    m = re.match(r"^(\d+[a-z]?)_(.*)$", n)
    if m:
        return "%s · %s" % (m.group(1), m.group(2).replace("_", " ").capitalize())
    return n.replace("_", " ").capitalize()


STATUS_STYLE = {
    "PASSED":  ("#047857", "#d1fae5", "PASS"),
    "FAILED":  ("#b91c1c", "#fee2e2", "FAIL"),
    "ERROR":   ("#b45309", "#fef3c7", "ERROR"),
    "SKIPPED": ("#475569", "#e2e8f0", "SKIP"),
}


def tests_table_html(run, compact=False):
    """One row per test, in execution order, with status and (for
    failures) the first assertion line. Shared by the mail body and the
    PDF so both always agree."""
    tests = run.get("tests") or []
    reasons = {f.get("test", "").split("[")[0]: f.get("reason", "") for f in (run.get("failures") or [])}
    if not tests:
        return "<p style='font-size:12px;color:#64748b'>No per-test results were recorded for this run.</p>"
    rows = ""
    for i, t in enumerate(tests, 1):
        status = t.get("status", "").upper()
        colour, bg, label = STATUS_STYLE.get(status, ("#475569", "#e2e8f0", status))
        reason = t.get("reason") or reasons.get(t.get("name", "").split("[")[0], "")
        reason_html = ("<div style='font-size:11px;color:#7f1d1d;margin-top:3px'>%s</div>" % _esc(reason)) if reason and status != "PASSED" else ""
        rows += (
            "<tr>"
            "<td style='padding:7px 8px;border-bottom:1px solid #e2e8f0;font-size:11px;color:#94a3b8;width:28px'>%d</td>"
            "<td style='padding:7px 8px;border-bottom:1px solid #e2e8f0;font-size:12px;color:#0f172a'>%s"
            "%s%s</td>"
            "<td style='padding:7px 8px;border-bottom:1px solid #e2e8f0;text-align:right;width:70px'>"
            "<span style='display:inline-block;padding:2px 9px;border-radius:999px;font-size:10.5px;font-weight:700;color:%s;background:%s'>%s</span></td>"
            "</tr>" % (i, _esc(_pretty_test_name(t.get("name", ""))),
                       ("<div style='font-family:Consolas,monospace;font-size:10.5px;color:#64748b'>%s</div>" % _esc(t["name"])) if t.get("name", "").startswith("test_") else "",
                       reason_html, colour, bg, label)
        )
    return ("<table role='presentation' width='100%%' cellspacing='0' cellpadding='0' "
            "style='border:1px solid #e2e8f0;border-radius:8px;border-collapse:separate;overflow:hidden;background:#fff'>"
            "<tr style='background:#f1f5f9'><th style='padding:7px 8px;font-size:10.5px;color:#475569;text-align:left'>#</th>"
            "<th style='padding:7px 8px;font-size:10.5px;color:#475569;text-align:left'>Test case</th>"
            "<th style='padding:7px 8px;font-size:10.5px;color:#475569;text-align:right'>Result</th></tr>%s</table>" % rows)


def build_pdf_html(run):
    """Full A4 report page."""
    total = run.get("tests_total") or len(run.get("tests") or [])
    passed = run.get("passed") or 0
    failed = run.get("failed") or 0
    errors = run.get("errors") or 0
    skipped = run.get("skipped") or 0
    ok = run.get("status") == "done" and run.get("exit_code") == 0
    stopped = run.get("status") == "stopped"
    when = datetime.datetime.fromtimestamp(run.get("started_at") or 0).strftime("%A, %d %B %Y at %H:%M")
    duration = _fmt_duration((run.get("finished_at") or 0) - (run.get("started_at") or 0))
    verdict = "STOPPED" if stopped else ("PASSED" if ok else "FAILED")
    colour = "#b45309" if stopped else ("#047857" if ok else "#b91c1c")
    rate = (100.0 * passed / total) if total else 0.0
    options = run.get("options") or {}

    meta = [("Suite", run.get("label", "")), ("Executed", when), ("Duration", duration),
            ("Run by", "%s, %s" % (AUTHOR, AUTHOR_TITLE)), ("Environment", "Retail POS · demo-backoffice.example.com · DemoStore DB")]
    if run.get("audit_code"):
        meta.append(("Audit code", run["audit_code"]))
    if run.get("seed"):
        meta.append(("Replay seed", str(run["seed"])))
    if options.get("env_tag"):
        meta.append(("Test data", "reused environment %s" % options["env_tag"]))
    meta_rows = "".join("<tr><td style='padding:3px 16px 3px 0;color:#64748b;white-space:nowrap'>%s</td><td style='padding:3px 0'>%s</td></tr>" % (k, _esc(v)) for k, v in meta)

    def tile(label, value, c):
        return ("<td style='padding:4px'><div style='border:1px solid #e2e8f0;border-radius:10px;padding:10px;text-align:center;background:#f8fafc'>"
                "<div style='font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#64748b'>%s</div>"
                "<div style='font-size:24px;font-weight:800;color:%s;line-height:1.2'>%s</div></div></td>" % (label, c, value))

    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 16mm 14mm 18mm 14mm; }
  body { font-family: 'Segoe UI', Inter, Arial, sans-serif; color: #0f172a; font-size: 12px; margin: 0; }
  h1 { font-size: 20px; margin: 0; }
  .muted { color: #64748b; }
  .footer { margin-top: 18px; padding-top: 8px; border-top: 1px solid #e2e8f0; font-size: 9.5px; color: #94a3b8; display: flex; justify-content: space-between; }
</style></head><body>
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" style="border-bottom:3px solid %(colour)s;padding-bottom:10px">
  <tr>
    <td><div style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#64748b">Retail POS · Test Automation Report</div>
        <h1>%(label)s</h1>
        <div class="muted" style="margin-top:2px">%(when)s · %(duration)s</div></td>
    <td align="right" style="vertical-align:top"><div style="display:inline-block;padding:8px 16px;border-radius:10px;background:%(colour)s;color:#fff;font-weight:800;font-size:16px;letter-spacing:.06em">%(verdict)s</div>
        <div class="muted" style="margin-top:4px">pass rate %(rate).0f%%</div></td>
  </tr>
</table>

<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" style="margin-top:14px"><tr>
  %(tiles)s
</tr></table>

<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" style="margin-top:14px"><tr>
  <td style="vertical-align:top;width:58%%"><table cellspacing="0" cellpadding="0" style="font-size:12px">%(meta)s</table></td>
  <td style="vertical-align:top;padding-left:16px">
    <div style="border-left:4px solid %(colour)s;background:#f8fafc;padding:10px 12px;border-radius:0 8px 8px 0;font-size:12px;line-height:1.5">%(summary)s</div>
  </td>
</tr></table>

<div style="font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#475569;margin:18px 0 8px">Test cases (%(n)d)</div>
%(table)s

<div style="margin-top:22px;font-size:12px;line-height:1.6">
  Every check above was executed automatically against the live POS application (desktop exe and backend web) and verified against the database where applicable.
  Failed checks list the assertion that stopped them; the automation console holds the full step log and screenshots for each.<br><br>
  <b>%(author)s</b><br><span class="muted">%(title)s · QA Automation</span>
</div>

<div class="footer"><span>Generated automatically by the POS Automation Console · %(generated)s</span><span>%(author)s · %(title)s</span></div>
</body></html>""" % {
        "colour": colour, "label": _esc(run.get("label", "Suite")), "when": when, "duration": duration,
        "verdict": verdict, "rate": rate,
        "tiles": tile("Total", total, "#1e293b") + tile("Passed", passed, "#047857") + tile("Failed", failed, "#b91c1c") +
                 tile("Errors", errors, "#b45309") + tile("Skipped", skipped, "#475569"),
        "meta": meta_rows,
        "summary": ("The run was stopped manually; results are partial." if stopped else
                    "All %d checks passed. No action is required from the development team." % total if ok else
                    "%d of %d checks did not pass. Each failing check and its reason is listed in the table; the ones marked FAIL are assertion failures, ERROR means the check could not complete." % (failed + errors, total)),
        "n": len(run.get("tests") or []), "table": tests_table_html(run),
        "author": AUTHOR, "title": AUTHOR_TITLE,
        "generated": datetime.datetime.now().strftime("%d %b %Y %H:%M"),
    }


def make_pdf(run, path=None):
    """Render the report to PDF with headless Chromium. Returns the path."""
    from playwright.sync_api import sync_playwright
    os.makedirs(REPORTS_DIR, exist_ok=True)
    if not path:
        stamp = datetime.datetime.fromtimestamp(run.get("started_at") or 0).strftime("%Y%m%d_%H%M")
        slug = re.sub(r"[^a-z0-9]+", "-", (run.get("label") or "run").lower()).strip("-")
        path = os.path.join(REPORTS_DIR, "%s_%s.pdf" % (slug, stamp))
    html = build_pdf_html(run)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=path, format="A4", print_background=True,
                 margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
        browser.close()
    return path
