# ============================================================
# DASHBOARD APP - a small local control panel for running the
# pos_framework pytest suites without typing terminal commands.
# Wraps the existing test files as-is; no test logic lives here.
# ============================================================

import os
import subprocess

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory

import backoffice_catalog
import branch_settings
import mailer
import runner
import exe_settings

app = Flask(__name__)

ALLURE_REPORT_DIR = os.path.join(runner.POS_FRAMEWORK_DIR, "allure-report")
# Web Report Verification gets its own separate report dir (see runner.py)
# so its history isn't mixed in with 19+ days of exe-suite results piled
# into the shared one.
ALLURE_REPORT_DIR_WEB = os.path.join(runner.POS_FRAMEWORK_DIR, "allure-report-web")
ALLURE_REPORT_DIR_AUDIT = os.path.join(runner.POS_FRAMEWORK_DIR, "allure-report-audit")
ALLURE_REPORT_DIR_SESSION = os.path.join(runner.POS_FRAMEWORK_DIR, "allure-report-session")


@app.route("/")
def index():
    environments, _ = backoffice_catalog.apps()
    return render_template("index.html", suites=runner.SUITES,
                           last=runner.last_results(), backoffice_apps=environments)


# ============================================================
# BACK OFFICE - one page per environment.
#
# The exe suites are a single button each: they run one long scripted
# flow and the only question is "did it pass". The back office is not
# like that. It is many independent checks across many modules, and the
# useful questions are "what does this suite cover", "what is mapped for
# THIS app", and "re-run just that one". That needs a page, not a
# button - which is why these suites are hidden from the home list and
# given one of their own.
# ============================================================

@app.route("/backoffice")
def backoffice_home():
    environments, _ = backoffice_catalog.apps()
    if not environments:
        return "No back-office environments found - check backoffice/profiles.", 404
    return redirect("/backoffice/" + environments[0]["key"])


@app.route("/backoffice/<app_key>")
def backoffice_app(app_key):
    environments, error = backoffice_catalog.apps()
    chosen = backoffice_catalog.app(app_key)
    if chosen is None:
        abort(404, "Unknown environment %r%s" % (app_key, (" - " + error) if error else ""))
    return render_template("backoffice.html", environment=chosen,
                           environments=environments, suite_key="backoffice_" + app_key)


@app.route("/api/backoffice/<app_key>/catalog")
def api_backoffice_catalog(app_key):
    """The whole page's data: modules, tests, and how each last did.

    Rebuilt from source whenever a test file changes, so a test written
    a minute ago is on the page after a refresh - nothing to register."""
    data = backoffice_catalog.catalog(app_key)
    if data is None:
        return jsonify({"ok": False, "message": "unknown environment"}), 404
    data["ok"] = True
    data["suite_key"] = "backoffice_" + app_key
    return jsonify(data)


@app.route("/api/backoffice/<app_key>/run", methods=["POST"])
def api_backoffice_run(app_key):
    """Run the whole suite, one module, or one test - same command
    either way, only the target differs (see runner._apply_selection)."""
    if backoffice_catalog.app(app_key) is None:
        return jsonify({"ok": False, "message": "unknown environment"}), 404
    body = request.get_json(silent=True) or {}
    targets = body.get("targets") or []
    if not isinstance(targets, list):
        return jsonify({"ok": False, "message": "targets must be a list"}), 400
    options = {"targets": [str(t) for t in targets][:200],
               "headed": bool(body.get("headed")),
               "scope": body.get("scope") or "suite"}
    ok, message = runner.start_run("backoffice_" + app_key, options)
    return jsonify({"ok": ok, "message": message})


@app.route("/report-backoffice-<app_key>/")
@app.route("/report-backoffice-<app_key>/<path:filename>")
def report_backoffice(app_key, filename="index.html"):
    if backoffice_catalog.app(app_key) is None:
        abort(404)
    folder = os.path.join(backoffice_catalog.RESULTS_ROOT,
                          "allure-report-backoffice-" + app_key)
    if not os.path.exists(os.path.join(folder, "index.html")):
        return "No report for this environment yet - run its suite first.", 404
    return send_from_directory(folder, filename)


@app.route("/api/history")
def api_history():
    return jsonify({"history": runner.load_history(), "last": runner.last_results()})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    runner.clear_history()
    return jsonify({"ok": True})


@app.route("/api/audit-partial")
def api_audit_partial():
    """Runs whose suppliers exist but whose items are incomplete - the
    build can resume from Item Profile instead of starting over."""
    import sys
    if runner.POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, runner.POS_FRAMEWORK_DIR)
    try:
        import db_helpers as db
        rows = db.query(
            "SELECT SUBSTRING(PartnerName, CHARINDEX('(AUTO ', PartnerName) + 6, 12) AS tag, "
            "       COUNT(*) AS suppliers "
            "FROM dbo.Partner WHERE PartnerName LIKE '%(AUTO %' AND PartnerTypeId = 2 "
            "GROUP BY SUBSTRING(PartnerName, CHARINDEX('(AUTO ', PartnerName) + 6, 12) "
            "ORDER BY tag DESC")
        out = []
        for r in rows[:10]:
            items = db.query("SELECT COUNT(*) AS c FROM dbo.Item WHERE ItemName LIKE ?",
                             ["%%(AUTO %s-%%" % r["tag"]])[0]["c"]
            out.append({"tag": r["tag"], "suppliers": r["suppliers"], "items": items})
        return jsonify({"ok": True, "envs": out})
    except Exception as e:
        return jsonify({"ok": False, "envs": [], "message": str(e)[:200]})


@app.route("/api/mail-status")
def api_mail_status():
    cfg = mailer.settings()
    return jsonify({"configured": cfg["configured"], "to": cfg["to"], "cc": cfg["cc"],
                    "host": cfg["host"], "from": cfg["from"]})


@app.route("/api/mail-preview")
def api_mail_preview():
    """Render the mail for the last finished run (or a sample) so the
    body can be checked in the browser before anything is sent."""
    st = runner.get_status()
    if st.get("status") not in ("done", "stopped"):
        hist = runner.load_history()
        st = hist[0] if hist else {
            "label": "Positive Flow", "status": "done", "exit_code": 1, "tests_total": 24,
            "passed": 22, "failed": 1, "errors": 1, "skipped": 0, "started_at": __import__("time").time() - 900,
            "finished_at": __import__("time").time(),
            "failures": [{"test": "test_04a_return_quantity_validation",
                          "reason": "AssertionError: Return validation failed on ['cart_zero_blocked'] (sample)"}],
            "report_route": "/report/", "options": {}}
    link = mailer.report_url(st.get("report_route") or "/report/")
    return mailer.build_html(st, link)


@app.route("/api/mail-test", methods=["POST"])
def api_mail_test():
    """Send the preview mail for real - to confirm SMTP works."""
    hist = runner.load_history()
    st = hist[0] if hist else None
    if not st:
        return jsonify({"ok": False, "message": "no finished run to send yet"})
    ok, message = mailer.send(st, st.get("report_route") or "/report/")
    return jsonify({"ok": ok, "message": message})


@app.route("/api/db-status")
def api_db_status():
    import sys
    if runner.POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, runner.POS_FRAMEWORK_DIR)
    try:
        import db_helpers as db
        ok = db.is_available()
        return jsonify({"ok": ok, "reason": None if ok else (db.unavailable_reason() or "")[:120]})
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)[:120]})


@app.route("/api/exe-settings")
def api_exe_settings():
    return jsonify(exe_settings.read())


@app.route("/api/exe-settings", methods=["POST"])
def api_exe_settings_set():
    body = request.get_json(silent=True) or {}
    if "group_flag" not in body:
        return jsonify({"ok": False, "message": "group_flag missing"}), 400
    ok, message = exe_settings.set_group_flag(bool(body["group_flag"]))
    exe_settings.invalidate_cache()
    state = exe_settings.read()
    if ok and state["exe_running"]:
        message += " - restart the POS exe to apply"
    return jsonify({"ok": ok, "message": message, "state": state})


@app.route("/api/exe-settings/invoice", methods=["POST"])
def api_exe_settings_invoice():
    body = request.get_json(silent=True) or {}
    ok, message = exe_settings.set_invoice_template(body.get("sale"), body.get("reprint"))
    exe_settings.invalidate_cache()
    state = exe_settings.read()
    if ok and state["exe_running"]:
        message += " - restart the POS exe to apply"
    return jsonify({"ok": ok, "message": message, "state": state})


@app.route("/api/branch-settings")
def api_branch_settings():
    """Every branch and whether its prices include VAT."""
    return jsonify(branch_settings.read())


@app.route("/api/branch-settings/vat", methods=["POST"])
def api_branch_settings_vat():
    """Turn VAT-inclusive pricing on or off for one branch.

    This changes what a whole outlet does, so the branch is named
    explicitly - there is no "apply to all".
    """
    body = request.get_json(silent=True) or {}
    if "branch_id" not in body or "value" not in body:
        return jsonify({"ok": False, "message": "branch_id and value are required"}), 400
    ok, message = branch_settings.set_vat_inclusive(body["branch_id"], bool(body["value"]))
    return jsonify({"ok": ok, "message": message, "state": branch_settings.read()})


@app.route("/api/run/<suite_key>", methods=["POST"])
def api_run(suite_key):
    options = request.get_json(silent=True) or {}
    ok, message = runner.start_run(suite_key, options)
    return jsonify({"ok": ok, "message": message})


@app.route("/api/audit-envs")
def api_audit_envs():
    """Environments the audit suite built earlier (suppliers named
    AUTO-SUP-<tag>-n), newest first, so the UI can offer "reuse" instead
    of rebuilding 24+ items every run. Read-only, via db_helpers."""
    import sys
    if runner.POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, runner.POS_FRAMEWORK_DIR)
    try:
        import db_helpers as db
        rows = db.query(
            "SELECT SUBSTRING(PartnerName, CHARINDEX('(AUTO ', PartnerName) + 6, 12) AS tag, "
            "       COUNT(*) AS suppliers, MIN(dtePartnerCreateDate) AS created "
            "FROM dbo.Partner WHERE PartnerName LIKE '%(AUTO %' AND PartnerTypeId = 2 "
            "GROUP BY SUBSTRING(PartnerName, CHARINDEX('(AUTO ', PartnerName) + 6, 12) "
            "ORDER BY tag DESC")
        out = []
        for r in rows:
            items = db.query("SELECT COUNT(*) AS c FROM dbo.Item WHERE ItemName LIKE ?",
                             ["%%(AUTO %s-%%" % r["tag"]])[0]["c"]
            if items:      # a tag with no items cannot be audited - hide it
                out.append({"tag": r["tag"], "suppliers": r["suppliers"], "items": items})
        return jsonify({"ok": True, "envs": out})
    except Exception as e:
        return jsonify({"ok": False, "envs": [], "message": str(e)[:200]})


@app.route("/api/status")
def api_status():
    return jsonify(runner.get_status())


@app.route("/api/logs")
def api_logs():
    since = request.args.get("since", 0, type=int)
    return jsonify(runner.get_logs(since))


@app.route("/api/stop", methods=["POST"])
def api_stop():
    ok, message = runner.stop_run()
    return jsonify({"ok": ok, "message": message})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    ok, message = runner.reset_state()
    return jsonify({"ok": ok, "message": message})


@app.route("/api/clear-logs", methods=["POST"])
def api_clear_logs():
    runner.clear_logs()
    return jsonify({"ok": True})


@app.route("/api/app-status")
def api_app_status():
    # Matching MainWindowTitle alone is not enough - the dashboard's own
    # page title is "POS App Pos Dashboard", so a browser tab showing
    # it also matches '*POSAPP*' (see runner.py's _close_exe_if_running
    # for the same bug, which was destructive there). ProcessName -eq
    # 'POS' (the exe's actual process name, confirmed live - different
    # from its "POSAPP" display name) keeps this status check accurate.
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process | Where-Object { $_.MainWindowTitle -like '*POSAPP*' -and $_.ProcessName -eq 'POS' } "
         "| Select-Object -First 1).Id"],
        capture_output=True, text=True, timeout=15
    )
    pid = result.stdout.strip()
    return jsonify({"running": bool(pid), "pid": pid or None})


@app.route("/report/")
@app.route("/report/<path:filename>")
def report(filename="index.html"):
    if not os.path.isdir(ALLURE_REPORT_DIR):
        return "No report generated yet - run a suite first.", 404
    return send_from_directory(ALLURE_REPORT_DIR, filename)


@app.route("/report-web/")
@app.route("/report-web/<path:filename>")
def report_web(filename="index.html"):
    if not os.path.isdir(ALLURE_REPORT_DIR_WEB):
        return "No web verification report generated yet - run that suite first.", 404
    return send_from_directory(ALLURE_REPORT_DIR_WEB, filename)


@app.route("/report-session/")
@app.route("/report-session/<path:filename>")
def report_session(filename="index.html"):
    if not os.path.isdir(ALLURE_REPORT_DIR_SESSION):
        return "No session report generated yet - run the Session Open / Close suite first.", 404
    return send_from_directory(ALLURE_REPORT_DIR_SESSION, filename)


@app.route("/report-audit/")
@app.route("/report-audit/<path:filename>")
def report_audit(filename="index.html"):
    if not os.path.isdir(ALLURE_REPORT_DIR_AUDIT):
        return "No audit report generated yet - run the audit suite first.", 404
    return send_from_directory(ALLURE_REPORT_DIR_AUDIT, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
