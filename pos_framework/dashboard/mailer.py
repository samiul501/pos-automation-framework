# ============================================================
# MAILER - sends the run summary to the dev team once a suite has
# finished and its Allure report is generated.
#
# Credentials never live here. They come from pos_framework/.env
# (the same gitignored file db_helpers reads), keys:
#   SMTP_HOST      e.g. smtp.office365.com  /  smtp.gmail.com
#   SMTP_PORT      587 (STARTTLS)
#   SMTP_USER      the sender login
#   SMTP_PASSWORD  an APP password - plain account passwords are
#                  refused by both Office 365 and Gmail for SMTP
#   MAIL_FROM      display sender (defaults to SMTP_USER)
#   MAIL_TO        comma-separated recipients
#   MAIL_CC        optional, comma-separated
#   REPORT_BASE_URL optional - where the Allure report is reachable
#                  from the recipients' side (defaults to this
#                  machine's LAN address + dashboard port)
# ============================================================

import datetime
import os
import smtplib
import socket
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

import reporter

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
POS_FRAMEWORK_DIR = os.path.join(os.path.dirname(DASHBOARD_DIR), "pos_framework")

AUTHOR = "Samiul Islam"
AUTHOR_TITLE = "Junior SQA"


ENV_FILE = os.path.join(POS_FRAMEWORK_DIR, ".env")


def _load_env():
    """Read pos_framework/.env fresh on EVERY call and let the file win.

    db_helpers' loader uses os.environ.setdefault once at import, which
    is right for a short pytest process but wrong for the long-lived
    dashboard: values added to .env after the dashboard started were
    never seen, and the UI kept saying "not configured" while a fresh
    process could send fine. Re-reading here costs nothing."""
    values = {}
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.split("#", 1)[0].strip() if key.strip().startswith(("SMTP_", "MAIL_", "REPORT_")) else value.strip()
    except OSError:
        pass
    for key, value in values.items():
        if key.startswith(("SMTP_", "MAIL_", "REPORT_BASE_URL")):
            os.environ[key] = value
    return values


def settings():
    _load_env()
    s = {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from": os.getenv("MAIL_FROM", "") or os.getenv("SMTP_USER", ""),
        "to": [x.strip() for x in os.getenv("MAIL_TO", "").split(",") if x.strip()],
        "cc": [x.strip() for x in os.getenv("MAIL_CC", "").split(",") if x.strip()],
        "report_base": os.getenv("REPORT_BASE_URL", "").rstrip("/"),
        # individual = one mail per recipient, To: shows only themselves (default)
        # bcc        = one mail, everyone in Bcc ("undisclosed recipients")
        # open       = one mail, everyone visible in To/Cc
        "privacy": (os.getenv("MAIL_PRIVACY", "individual") or "individual").strip().lower(),
    }
    s["configured"] = bool(s["host"] and s["user"] and s["password"] and s["to"])
    return s


def _lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def report_url(report_route, port=5055):
    base = settings()["report_base"]
    if not base:
        base = "http://%s:%d" % (_lan_ip(), port)
    return base + (report_route or "/report/")


# ---- content -------------------------------------------------------

def _fmt_duration(seconds):
    seconds = int(seconds or 0)
    return "%dm %02ds" % (seconds // 60, seconds % 60)


def subject_for(run):
    total = run.get("tests_total") or 0
    passed = run.get("passed") or 0
    bad = (run.get("failed") or 0) + (run.get("errors") or 0)
    if run.get("status") == "stopped":
        verdict = "STOPPED"
    elif run.get("exit_code") == 0:
        verdict = "PASSED %d/%d" % (passed, total)
    else:
        verdict = "FAILED %d of %d" % (bad, total)
    when = datetime.datetime.fromtimestamp(run.get("started_at") or 0).strftime("%d %b %Y %H:%M")
    return "[POS Automation] %s — %s · %s" % (run.get("label", "Suite"), verdict, when)


def build_html(run, link):
    """A clean, client-safe HTML mail (tables + inline styles: Outlook
    has no love for modern CSS). Sections: verdict banner, summary
    tiles, what failed (if anything), report link, sign-off."""
    total = run.get("tests_total") or 0
    passed = run.get("passed") or 0
    failed = run.get("failed") or 0
    errors = run.get("errors") or 0
    skipped = run.get("skipped") or 0
    ok = run.get("status") == "done" and run.get("exit_code") == 0
    stopped = run.get("status") == "stopped"
    when = datetime.datetime.fromtimestamp(run.get("started_at") or 0).strftime("%A, %d %B %Y at %H:%M")
    duration = _fmt_duration((run.get("finished_at") or 0) - (run.get("started_at") or 0))

    if stopped:
        color, headline, intro = "#b45309", "Run stopped before completion", \
            "The suite was stopped manually before it could finish, so the results below are partial."
    elif ok:
        color, headline, intro = "#047857", "All checks passed", \
            "The automated regression completed successfully. No action is required from the development team."
    else:
        color, headline, intro = "#b91c1c", "Attention needed — %d check%s failed" % (failed + errors, "" if failed + errors == 1 else "s"), \
            "The automated regression found issues that need a look. The failing checks and their reasons are listed below, and the full evidence (steps, screenshots, logs) is in the Allure report."

    audit = run.get("audit_code")
    seed = run.get("seed")
    options = run.get("options") or {}
    extra = ""
    if audit:
        extra += "<tr><td style='padding:4px 0;color:#64748b'>Audit code</td><td style='padding:4px 0;font-family:Consolas,monospace'>%s</td></tr>" % audit
    if seed:
        extra += "<tr><td style='padding:4px 0;color:#64748b'>Replay seed</td><td style='padding:4px 0;font-family:Consolas,monospace'>%s</td></tr>" % seed
    if options.get("env_tag"):
        extra += "<tr><td style='padding:4px 0;color:#64748b'>Test data</td><td style='padding:4px 0'>reused environment %s</td></tr>" % options["env_tag"]

    fail_rows = ""
    for f in (run.get("failures") or [])[:10]:
        fail_rows += ("<tr><td style='padding:8px 10px;border-bottom:1px solid #fee2e2;font-family:Consolas,monospace;font-size:12px;color:#991b1b;white-space:nowrap'>%s</td>"
                      "<td style='padding:8px 10px;border-bottom:1px solid #fee2e2;font-size:12px;color:#374151'>%s</td></tr>"
                      % (_esc(f.get("test", "")), _esc(f.get("reason", ""))))
    failures_block = ""
    if fail_rows and False:   # superseded by the full per-test table
        failures_block = """
        <tr><td style="padding:22px 28px 0">
          <div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#991b1b;margin-bottom:8px">What failed</div>
          <table role="presentation" width="100%%" cellspacing="0" cellpadding="0" style="border:1px solid #fecaca;border-radius:8px;border-collapse:separate;overflow:hidden;background:#fff5f5">
            <tr style="background:#fee2e2"><th align="left" style="padding:8px 10px;font-size:11px;color:#7f1d1d">Test</th><th align="left" style="padding:8px 10px;font-size:11px;color:#7f1d1d">Reason</th></tr>
            %s
          </table>
        </td></tr>""" % fail_rows

    def tile(label, value, colour):
        return ("<td width='25%%' style='padding:6px'><div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 10px;text-align:center'>"
                "<div style='font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#64748b'>%s</div>"
                "<div style='font-size:26px;font-weight:800;color:%s;line-height:1.2;margin-top:2px'>%s</div></div></td>" % (label, colour, value))

    return """<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef2f7;font-family:Segoe UI,Inter,Arial,sans-serif;color:#0f172a">
<table role="presentation" width="100%%" cellspacing="0" cellpadding="0" style="background:#eef2f7;padding:28px 12px">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%%;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 10px 30px -18px rgba(2,6,23,.4)">

  <!-- header -->
  <tr><td style="background:linear-gradient(135deg,#1e1b4b,#312e81 60%%,#4c1d95);padding:22px 28px;color:#ffffff">
    <div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;opacity:.75">Retail POS · Automation</div>
    <div style="font-size:20px;font-weight:800;margin-top:4px">%(label)s</div>
    <div style="font-size:12px;opacity:.8;margin-top:2px">%(when)s · %(duration)s</div>
  </td></tr>

  <!-- verdict -->
  <tr><td style="padding:22px 28px 0">
    <div style="border-left:4px solid %(color)s;background:#f8fafc;border-radius:0 10px 10px 0;padding:12px 16px">
      <div style="font-size:16px;font-weight:700;color:%(color)s">%(headline)s</div>
      <div style="font-size:13px;color:#334155;margin-top:4px;line-height:1.5">%(intro)s</div>
    </div>
  </td></tr>

  <!-- tiles -->
  <tr><td style="padding:16px 22px 0">
    <table role="presentation" width="100%%" cellspacing="0" cellpadding="0"><tr>
      %(tiles)s
    </tr></table>
  </td></tr>

  <!-- details -->
  <tr><td style="padding:18px 28px 0">
    <table role="presentation" cellspacing="0" cellpadding="0" style="font-size:13px">
      <tr><td style="padding:4px 18px 4px 0;color:#64748b">Suite</td><td style="padding:4px 0">%(label)s</td></tr>
      <tr><td style="padding:4px 18px 4px 0;color:#64748b">Executed</td><td style="padding:4px 0">%(when)s</td></tr>
      <tr><td style="padding:4px 18px 4px 0;color:#64748b">Duration</td><td style="padding:4px 0">%(duration)s</td></tr>
      <tr><td style="padding:4px 18px 4px 0;color:#64748b">Run by</td><td style="padding:4px 0">%(author)s, %(title)s</td></tr>
      %(extra)s
    </table>
  </td></tr>

  %(failures)s

  <!-- all tests -->
  <tr><td style="padding:22px 28px 0">
    <div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#475569;margin-bottom:8px">Test results (%(n)d checks)</div>
    %(tests)s
  </td></tr>

  <!-- attachment note -->
  <tr><td style="padding:20px 28px 4px">
    <div style="border:1px dashed #c7d2fe;background:#eef2ff;border-radius:10px;padding:12px 14px;font-size:12px;color:#3730a3">
      &#128206; The detailed report is attached as a <b>PDF</b> (%(pdf_name)s) &mdash; every check with its result and, for failures, the exact assertion.
    </div>
  </td></tr>

  <!-- sign-off -->
  <tr><td style="padding:22px 28px 26px;font-size:13px;color:#334155;line-height:1.6">
    Please reach out if any result needs clarification — the report carries the exact step, input and screen state at the moment each check ran.<br><br>
    Best regards,<br>
    <b>%(author)s</b><br>
    <span style="color:#64748b">%(title)s · QA Automation</span>
  </td></tr>

  <tr><td style="background:#f1f5f9;padding:12px 28px;font-size:11px;color:#94a3b8">
    This message was generated automatically by the POS automation console after the suite finished. Do not reply to this address.
  </td></tr>
</table>
</td></tr></table>
</body></html>""" % {
        "label": _esc(run.get("label", "Suite")), "when": when, "duration": duration,
        "color": color, "headline": headline, "intro": intro,
        "tiles": tile("Passed", passed, "#047857") + tile("Failed", failed, "#b91c1c") +
                 tile("Errors", errors, "#b45309") + tile("Total", total, "#1e293b"),
        "extra": extra, "failures": failures_block, "link": link,
        "n": len(run.get("tests") or []), "tests": reporter.tests_table_html(run),
        "pdf_name": _esc(os.path.basename(run.get("pdf_path") or "report.pdf")),
        "author": AUTHOR, "title": AUTHOR_TITLE,
    }


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---- sending -------------------------------------------------------

def send(run, report_route, port=5055, dry_run=False):
    """Send the summary mail for `run` (a runner state / history entry).
    Returns (ok, message). dry_run builds everything but skips SMTP."""
    cfg = settings()
    if not cfg["configured"]:
        return False, "mail not configured - set SMTP_HOST/SMTP_USER/SMTP_PASSWORD/MAIL_TO in pos_framework/.env"

    link = report_url(report_route, port)
    msg = MIMEMultipart("mixed")
    body = MIMEMultipart("alternative")
    msg.attach(body)
    msg["Subject"] = subject_for(run)
    msg["From"] = "%s <%s>" % (AUTHOR + " (POS Automation)", cfg["from"])
    text = ("%s\n\nPassed %s / Failed %s / Errors %s of %s\nThe detailed PDF report is attached.\n\n%s, %s"
            % (subject_for(run), run.get("passed"), run.get("failed"), run.get("errors"),
               run.get("tests_total"), AUTHOR, AUTHOR_TITLE))
    body.attach(MIMEText(text, "plain", "utf-8"))
    body.attach(MIMEText(build_html(run, link), "html", "utf-8"))

    pdf_path = run.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        try:
            pdf_path = reporter.make_pdf(run)
            run["pdf_path"] = pdf_path
        except Exception as e:
            pdf_path = None
            text += "\n(PDF could not be generated: %s)" % str(e)[:120]
    if pdf_path:
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
        msg.attach(part)

    recipients = cfg["to"] + cfg["cc"]
    if dry_run:
        return True, "dry run - would send (%s) to %s" % (cfg["privacy"], recipients)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(cfg["user"], cfg["password"])
            if cfg["privacy"] == "open":
                msg["To"] = ", ".join(cfg["to"])
                if cfg["cc"]:
                    msg["Cc"] = ", ".join(cfg["cc"])
                smtp.sendmail(cfg["from"], recipients, msg.as_string())
                sent = len(recipients)
            elif cfg["privacy"] == "bcc":
                # Bcc never appears in the headers; the envelope carries it.
                msg["To"] = "Undisclosed recipients <%s>" % cfg["from"]
                smtp.sendmail(cfg["from"], recipients, msg.as_string())
                sent = len(recipients)
            else:
                # individual: each person gets their own copy with only
                # their address in To - nobody can tell who else got it.
                sent = 0
                for rcpt in recipients:
                    del msg["To"]
                    msg["To"] = rcpt
                    smtp.sendmail(cfg["from"], [rcpt], msg.as_string())
                    sent += 1
        return True, "sent %s to %d recipient(s)" % (cfg["privacy"], sent)
    except smtplib.SMTPAuthenticationError as e:
        return False, "SMTP login refused - use an APP password, not the account password (%s)" % str(e)[:120]
    except Exception as e:
        return False, "mail failed: %s" % str(e)[:200]
