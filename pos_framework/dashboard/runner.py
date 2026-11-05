# ============================================================
# RUNNER - manages running one pos_framework pytest suite at a
# time in a background thread, capturing its output for the
# dashboard to poll. No two suites can run concurrently since
# they all drive the same single live desktop app.
# ============================================================

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import mailer
import exe_settings
import reporter
import backoffice_catalog

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
POS_FRAMEWORK_DIR = os.path.join(os.path.dirname(DASHBOARD_DIR), "pos_framework")
VENV_PYTHON = os.path.join(os.path.dirname(DASHBOARD_DIR), "venv", "Scripts", "python.exe")
HISTORY_FILE = os.path.join(DASHBOARD_DIR, "run_history.json")
HISTORY_LIMIT = 60

# The audit flow narrates itself with "[audit_flow] ..." lines; these
# markers turn that narration into a step timeline for the UI. Order
# matters - a later marker implies the earlier steps are complete.
AUDIT_STEPS = [
    ("env",      "Build data",     re.compile(r"env: (tag=|suppliers ->|loaded)")),
    ("items",    "Items",          re.compile(r"env: item ")),
    ("receive",  "Direct receive", re.compile(r"env: received ")),
    ("setup",    "Audit setup",    re.compile(r"scope row staged|created IAU")),
    ("approve",  "Approve",        re.compile(r"approved=")),
    ("scan",     "Exe scan",       re.compile(r"audit codes offered|scan \S+ +expected")),
    ("sync",     "Fn+F1 sync",     re.compile(r"sync popup")),
    ("report",   "Report",         re.compile(r"report .*rows")),
    ("verify",   "Assertions",     re.compile(r"::test_\w+.*(PASSED|FAILED|ERROR)")),
]

SUITES = {
    # The repeated chores that come before any testing. These are plain
    # scripts, not pytest - a "script" key makes the runner call the file
    # directly instead of building a pytest command. They are first in this
    # dict so they render at the top of the page, above the suites.
    "setup_full": {
        "label": "Reset + Register + Session",
        "description": "Resets the app, takes a fresh token from the back office, registers, logs in and opens a session",
        "icon": "setup",
        "script": ["exe_setup/setup_tasks.py", "full"],
        "needs_exe_closed": True,
        "no_report": True,
        "group": "Exe Setup",
    },
    "setup_register": {
        "label": "Register + Session",
        "description": "No reset - token, registration, login and session open on the app as it is",
        "icon": "setup",
        "script": ["exe_setup/setup_tasks.py", "register"],
        "needs_exe_closed": True,
        "no_report": True,
        "group": "Exe Setup",
    },
    "setup_reset": {
        "label": "Reset Only",
        "description": "Resets the installed app and stops, leaving it clean for a manual run",
        "icon": "setup",
        "script": ["exe_setup/setup_tasks.py", "reset"],
        "needs_exe_closed": True,
        "no_report": True,
        "group": "Exe Setup",
    },
    "positive": {
        "label": "Positive Flow",
        "description": "Login, 6 transactions, Hold & Recall, Exchange, Return, Logout",
        "icon": "check",
        "args": ["positive_tests/test_pos_full.py"],
        "needs_exe_closed": True,
    },
    "negative": {
        "label": "Negative + Positive Flow",
        "description": "Negative cases per step, then one valid action to advance",
        "icon": "shield",
        "args": ["negative_tests/test_negative_positive_flow.py"],
        "needs_exe_closed": True,
    },
    # Kept as its own separate suite/button (not merged into "negative")
    # - positioned right after it in this dict only so it renders directly
    # below it in the UI list, since Jinja iterates SUITES in this order.
    # Also given its own results_dir/report_dir (see below) - the shared
    # allure-results had 19 days of mixed exe-suite history piled into it,
    # so there was no clean place to see just the web checks on their own.
    "web_verify": {
        "label": "Web Report Verification",
        "description": "Checks today's invoices + captured ones against the web report",
        "icon": "globe",
        "args": ["positive_tests/test_web_report_verification.py"],
        "needs_exe_closed": False,   # pure browser check, doesn't touch the exe
        "results_dir": "allure-results-web",
        "report_dir": "allure-report-web",
        "report_route": "/report-web/",
    },
    # Its own suite rather than a case inside "negative": the flow needs the
    # app reset and re-registered against sami2 before it starts, which no
    # other suite does and which would wipe the registration the exe suites
    # rely on. Given its own results folder for the same reason as web_verify
    # - so a session verdict is never mixed into the exe suites' history.
    "session": {
        "label": "Session Open / Close",
        "description": "Opens a session, sells, logs out, logs back in and closes it - checks the close reaches the server",
        "icon": "session",
        "args": ["session_tests/test_session_open_close.py"],
        "needs_exe_closed": True,
        "results_dir": "allure-results-session",
        "report_dir": "allure-report-session",
        "report_route": "/report-session/",
    },
    "full": {
        "label": "Full (Positive + Web Verify)",
        "description": "The complete positive flow, then web report verification",
        "icon": "layers",
        # Two STAGES, not one pytest run: the web-verification module reads
        # the captured-invoice file at collection time, and a single session
        # collects both files before the positive flow has written it - so
        # it would verify the PREVIOUS run's invoices. Stage 2 starts only
        # after stage 1 has finished writing.
        "stages": [["positive_tests/test_pos_full.py"],
                   ["positive_tests/test_web_report_verification.py"]],
        "args": ["positive_tests/test_pos_full.py", "positive_tests/test_web_report_verification.py"],
        "needs_exe_closed": True,
    },
    # One click = the whole supplier-wise audit chain in a single web
    # session: [build suppliers/items/stock] -> audit setup (one scope row
    # per supplier) -> approve -> exe scan + Fn+F1 -> DB -> Audit Summary
    # Report per supplier. Options (build vs reuse data, headed) arrive
    # from the UI as environment variables the test file already reads.
    "audit": {
        "label": "Supplier-wise Audit",
        "description": "Builds suppliers, items and stock, then audit setup, approval, exe scan and report check - one login",
        "icon": "audit",
        "args": ["audit_tests/test_audit_multi_scope.py"],
        "needs_exe_closed": True,
        "has_options": True,
        "results_dir": "allure-results-audit",
        "report_dir": "allure-report-audit",
        "report_route": "/report-audit/",
    },
    # Load test - drive the real POS exe through many back-to-back sales to
    # see it hold up under volume. A plain script (not pytest): it launches
    # the exe, logs in, and sells N items to each of M customers, clearing
    # the barcode box between items and handling the variant / out-of-stock
    # popups, verifying the cart after each add. no_report because it writes
    # no Allure results; its progress streams live to the console instead.
    # Online and Offline are two modes of ONE thing (the login path differs -
    # Offline ticks the IsOffline box - everything after login is identical),
    # so they are hidden from the normal suite loop and rendered together
    # inside a single "Load Test" card in the template. They stay real
    # suites here so /api/run, history and the running/last-run wiring all
    # work for each mode unchanged.
    "load_online": {
        "label": "Load Test - Online",
        "description": "Launches the exe and sells 30 items to each of 4 customers (online)",
        "icon": "layers",
        "script": ["load_test.py", "--mode", "online", "--customers", "4", "--items", "30"],
        "needs_exe_closed": True,
        "no_report": True,
        "hidden": True,
        "counts_sales": True,     # tiles count "SALE n OK/FAIL" lines - no pytest verdicts here
    },
    "load_offline": {
        "label": "Load Test - Offline",
        "description": "Same 4x30 sale with the IsOffline box ticked - runs fully offline",
        "icon": "layers",
        "script": ["load_test.py", "--mode", "offline", "--customers", "4", "--items", "30"],
        "needs_exe_closed": True,
        "no_report": True,
        "hidden": True,
        "counts_sales": True,     # tiles count "SALE n OK/FAIL" lines - no pytest verdicts here
    },
}


def _register_backoffice_suites():
    """One suite per back-office environment - built from the framework's
    own profile registry, not written out here.

    That is the whole point: adding backoffice/profiles/<new>.py gives
    the dashboard a new suite with no dashboard change at all. These
    suites carry their own pytest.ini (Playwright screenshot/video/trace
    options that must not reach the exe suites) and their own results
    folder per environment, so a DemoStore run and an StoreB run can
    never be mistaken for one another.
    """
    try:
        found, _ = backoffice_catalog.apps()
    except Exception:
        return
    for environment in found:
        key = environment["key"]
        SUITES["backoffice_" + key] = {
            "label": "Back Office - " + environment["label"],
            "description": "Menu-driven back-office checks against " + str(environment["base_url"]),
            "icon": "globe",
            "args": ["backoffice", "-c", "backoffice/pytest.ini", "--app", key],
            "needs_exe_closed": False,        # browser only, never touches the exe
            "results_dir": environment["results_dir"],
            "report_dir": environment["report_dir"],
            "report_route": environment["report_route"],
            # this suite can run a subset: one module, or one test
            "selectable": True,
            "backoffice_app": key,
            "hidden": True,                   # it has its own page, not a home-page button
        }


_register_backoffice_suites()


def _apply_selection(suite, stage_args):
    """Narrow a run to the modules or tests the page asked for.

    The suite normally points pytest at the whole `backoffice` folder.
    When the page asks for one module or one test, that folder argument
    is swapped for the chosen paths - everything else about the run
    (config file, app, allure dir) stays exactly the same, so a single
    test runs under identical conditions to the full suite.

    Targets arrive relative to backoffice/tests, e.g.
        configuration/test_item_create.py::test_creates_a_new_item
        configuration
    and are anchored here rather than in the browser, so nothing outside
    the suite can be reached from the page.
    """
    if not suite.get("selectable"):
        return stage_args
    with _lock:
        targets = list((_state.get("options") or {}).get("targets") or [])
    if not targets:
        return stage_args

    resolved = []
    for target in targets:
        cleaned = str(target).replace("\\", "/").strip().lstrip("/")
        if not cleaned or ".." in cleaned.split("/"):
            continue
        resolved.append("backoffice/tests/" + cleaned)
    if not resolved:
        return stage_args

    # stage_args[0] is the folder the suite normally runs; the rest are
    # its flags (-c, --app ...) and must be kept.
    return resolved + list(stage_args[1:])


def _close_exe_if_running():
    """Every suite that drives the exe assumes it starts from the login
    screen. Confirmed live (2026-08-22): if POSAPP is already open and
    logged in (e.g. left over from a manual investigation), test_01_login
    can't find the login fields and times out, then every later test
    cascades to failure too - even though test_06_logout still passes,
    since the app genuinely was logged in. Closing any existing instance
    first guarantees every run starts clean.

    CONFIRMED BUG, FIXED (2026-09-02): matching on MainWindowTitle alone
    was too broad - the dashboard's own page title is "POS App Pos
    Dashboard", so a browser window with that tab active/focused shows a
    window title like "POS App Pos Dashboard - Google Chrome", which
    also matched '*POSAPP*' and got force-closed, killing the user's
    entire Chrome (including the dashboard tab itself) every time a suite
    ran while they were watching it. Now also requires ProcessName to be
    the actual exe's process (confirmed live: "POS", not "POSAPP" -
    the display name and the .exe process name differ), and explicitly
    excludes common browser process names as a second layer of defense in
    case the exe's process name ever changes again in a future build."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { "
         "$_.MainWindowTitle -like '*POSAPP*' -and "
         "$_.ProcessName -eq 'POS' -and "
         "$_.ProcessName -notin @('chrome','msedge','firefox') "
         "} | ForEach-Object { Stop-Process -Id $_.Id -Force }"],
        capture_output=True, text=True, timeout=15
    )
    time.sleep(1)

_lock = threading.Lock()
_state = {
    "status": "idle",       # idle | running | done | stopped
    "suite": None,
    "label": None,
    "log_lines": [],
    "exit_code": None,
    "started_at": None,
    "finished_at": None,
    "report_ready": False,
    "report_route": "/report/",
    "extra_env": {},        # per-run environment overrides (audit options)
    "options": {},          # the options the UI sent (shown in history)
    # live progress, derived from the log as it streams
    "tests_total": 0,
    "passed": 0,
    "failed": 0,
    "errors": 0,
    "skipped": 0,
    "current_test": None,
    "failures": [],         # [{test, reason}] - first assertion line per failed test
    "tests": [],            # [{name, status}] every test in execution order
    "pdf_path": None,
    "audit_steps": [],      # [{key,label,state}] for the audit suite
    "audit_code": None,
    "seed": None,
    "mail": None,           # {"ok": bool, "message": str} once a mail was attempted
}
_current_process = None    # the live Popen for the running suite, if any
_stop_requested = False    # set by stop_run(); _run_in_thread checks this to avoid
                            # racing a normal completion with a stop request


def get_status():
    with _lock:
        return {k: v for k, v in _state.items() if k != "log_lines" and not k.startswith("_")}


def get_logs(since=0):
    with _lock:
        lines = _state["log_lines"][since:]
        total = len(_state["log_lines"])
    return {"lines": lines, "next": total}


def clear_logs():
    """Clears the log display only - does not touch a run in progress.
    Safe to call anytime, running or not."""
    with _lock:
        _state["log_lines"] = []


def _selfcheck_before_run():
    """Run the framework's own sanity pass before a suite starts.

    It takes a couple of seconds and needs nothing but the source, and it
    catches the kind of damage an edit does to code that was already
    working - a module that no longer imports, a helper that was renamed,
    a statement stranded after a return. Finding that here costs seconds;
    finding it half way through a 13-minute exe run costs the run.

    A problem is reported in the log but does NOT block the suite: the
    operator decides. A crash inside the check itself is ignored entirely -
    a broken guard must never stop real work."""
    try:
        sys.path.insert(0, os.path.join(POS_FRAMEWORK_DIR, "tools"))
        import selfcheck
        importlib.reload(selfcheck)
        result = selfcheck.run()
    except Exception as e:
        return ["--- Self check could not run: " + str(e)[:160] + " ---"]
    if result.ok:
        return ["--- Self check passed (" + "; ".join(result.notes) + ") ---"]
    lines = ["--- SELF CHECK FOUND %d PROBLEM(S) - the suite will still run ---" % len(result.problems)]
    for area, message in result.problems[:12]:
        lines.append("---   [" + area + "] " + message + " ---")
    return lines


def _run_in_thread(suite_key):
    global _current_process, _stop_requested
    suite = SUITES[suite_key]
    results_dir = suite.get("results_dir", "allure-results")
    report_dir = suite.get("report_dir", "allure-report")

    # DO THE SLOW PART FIRST, THEN TAKE THE LOCK.
    #
    # The self check imports the whole framework. Doing that while
    # holding _lock deadlocks the dashboard: this thread waits on
    # Python's import lock for a module, while a request thread that
    # already holds that import lock calls get_status() and waits on
    # _lock. Both stop, /api/status stops answering, and the page hangs
    # with no error anywhere. The lock is only ever for touching
    # _state - never for work.
    selfcheck_lines = _selfcheck_before_run()
    with _lock:
        _state["log_lines"].extend(selfcheck_lines)

    if suite["needs_exe_closed"]:
        with _lock:
            _state["log_lines"].append("--- Ensuring POSAPP is closed before starting (clean state) ---")
        _close_exe_if_running()
        # The group-discount switch lives only in the exe's local cache and a
        # reinstall resets it to OFF (see exe_settings.py). With the pin on,
        # re-assert it now - the exe is closed, so it starts with the value.
        with _lock:
            pin = bool(_state.get("options", {}).get("group_flag_pin"))
        if pin:
            msg = exe_settings.enforce_group_flag_on()
            with _lock:
                _state["log_lines"].append("--- " + msg + " ---")

    run_env = dict(os.environ)
    run_env["PYTHONIOENCODING"] = "utf-8"
    # A suite can pin environment variables of its own - the two
    # back-office entries use this to choose which app they target.
    run_env.update({k: str(v) for k, v in suite.get("env", {}).items()})
    with _lock:
        run_env.update({k: str(v) for k, v in _state.get("extra_env", {}).items() if v not in (None, "")})

    # Fresh results for THIS run only: leftover results from earlier runs
    # (e.g. the pre-split single web-verification test) would otherwise be
    # merged into the new Allure report as if they had just run.
    #
    # UNLESS only part of the suite was asked for. Re-running one test
    # must not erase what the other ten did - the back-office page shows
    # every test's last verdict, and wiping would blank the lot. Allure
    # writes a new file per run and the page keeps the newest per test,
    # so adding to the folder is the correct behaviour here.
    with _lock:
        partial = bool((_state.get("options") or {}).get("targets"))
    results_path = os.path.join(POS_FRAMEWORK_DIR, results_dir)
    if partial:
        with _lock:
            _state["log_lines"].append(
                "--- Running a subset: keeping the other tests' earlier results ---")
    else:
        shutil.rmtree(results_path, ignore_errors=True)
    os.makedirs(results_path, exist_ok=True)

    with _lock:
        watch_browser = bool((_state.get("options") or {}).get("headed"))

    script = suite.get("script")
    stages = [script] if script else (suite.get("stages") or [suite["args"]])
    returncode = 0
    for n, stage_args in enumerate(stages, 1):
        if script:
            # A plain script: run the file, do not wrap it in pytest and do
            # not ask it for Allure results it never writes. -u so its
            # progress reaches the page as it happens rather than in one
            # lump when it finishes.
            cmd = [VENV_PYTHON, "-u"] + list(stage_args)
        else:
            stage_args = _apply_selection(suite, stage_args)
            cmd = [VENV_PYTHON, "-m", "pytest"] + stage_args + ["--alluredir=" + results_dir, "-v"]
        # "Watch browser" on the back-office page. The suite's own conftest
        # turns --headed into a maximised window with no fixed viewport, so
        # the run fills the screen rather than sitting in a 1920x1080 box.
        # Only for suites that drive a browser - the exe suites are always
        # visible anyway and have no such flag.
        if suite.get("selectable") and watch_browser:
            cmd += ["--headed", "--slowmo", "250"]

        # Show the exact command. It is the difference between "it ran"
        # and "it ran the way I asked", and it can be pasted into a
        # terminal to repeat the run by hand.
        with _lock:
            _state["log_lines"].append(
                "--- " + subprocess.list2cmdline(cmd[1:]) + " ---")
        if suite.get("has_options"):
            cmd.append("-s")            # the audit flow narrates its steps; show them live
        if len(stages) > 1:
            with _lock:
                _state["log_lines"].append("--- Stage %d/%d: %s ---" % (n, len(stages), " ".join(stage_args)))

        # CREATE_NEW_PROCESS_GROUP so stop_run() can taskkill this whole tree
        # (pytest -> pywinauto/playwright's own child processes) - terminating
        # only the top pytest process would leave a launched browser or the
        # exe orphaned and still running.
        process = subprocess.Popen(
            cmd, cwd=POS_FRAMEWORK_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            env=run_env, encoding="utf-8", errors="replace"
        )
        with _lock:
            _current_process = process

        for line in process.stdout:
            line = line.rstrip("\n")
            with _lock:
                _state["log_lines"].append(line)
                _ingest_progress(line, suite)
        process.wait()
        returncode = max(returncode, process.returncode)
        with _lock:
            if _stop_requested:
                break

    with _lock:
        was_stopped = _stop_requested
        _stop_requested = False
        _current_process = None

    if was_stopped:
        with _lock:
            _state["status"] = "stopped"
            _state["exit_code"] = returncode
            _state["finished_at"] = time.time()
            _state["log_lines"].append("--- Stopped by user ---")
            _finish_audit_steps(returncode, stopped=True)
            _record_history()
        return

    # The Exe Setup chores are plain scripts with no tests in them. Building
    # an Allure report and a PDF out of an empty results folder produced an
    # empty report and a pointless PDF on every run, so skip both.
    if suite.get("no_report"):
        with _lock:
            _state["log_lines"].append("")
            _state["log_lines"].append(
                "--- Done (exit code " + str(returncode) + ") ---")
            # "done" is the word the page checks for a green verdict; a run
            # that ended cleanly must not be shown as a failure just because
            # it had no tests to count.
            _state["status"] = "done"
            _state["finished_at"] = time.time()
            _state["exit_code"] = returncode
            _state["report_ready"] = False
        _record_history()
        return

    with _lock:
        _state["log_lines"].append("")
        _state["log_lines"].append("--- Generating Allure report ---")

    subprocess.run(
        ["allure", "generate", "--clean", "-o", report_dir, results_dir],
        cwd=POS_FRAMEWORK_DIR, capture_output=True, text=True, shell=True
    )

    with _lock:
        _state["status"] = "done"
        _state["exit_code"] = returncode
        _state["finished_at"] = time.time()
        _state["report_ready"] = True
        _state["report_route"] = suite.get("report_route", "/report/")
        _state["log_lines"].append("--- Done (exit code " + str(returncode) + ") ---")
        _finish_audit_steps(returncode, stopped=False)
        want_mail = bool((_state.get("options") or {}).get("email"))
        snapshot = {k: v for k, v in _state.items() if k != "log_lines" and not k.startswith("_")}

    # Prefer Allure's own titles/statuses for the test list: they carry the
    # serial numbers the operator sees in the Allure report, so PDF + mail
    # never disagree with it.
    allure_tests = _tests_from_allure(os.path.join(POS_FRAMEWORK_DIR, results_dir))
    if allure_tests:
        # The counters too, not just the list: the live log parse can miss
        # verdicts, and the tiles must agree with the list under them.
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for t in allure_tests:
            key = {"PASSED": "passed", "FAILED": "failed", "ERROR": "errors", "SKIPPED": "skipped"}.get(t["status"])
            if key:
                counts[key] += 1
        with _lock:
            _state["tests"] = allure_tests
            _state.update(counts)
        snapshot["tests"] = allure_tests
        snapshot.update(counts)

    # PDF report (every test with its verdict) - the artefact that travels
    # with the mail, since the Allure report is only reachable locally.
    try:
        pdf = reporter.make_pdf(snapshot)
        with _lock:
            _state["pdf_path"] = pdf
            _state["log_lines"].append("--- PDF report: " + pdf + " ---")
        snapshot["pdf_path"] = pdf
    except Exception as e:
        with _lock:
            _state["log_lines"].append("--- PDF report failed: " + str(e)[:160] + " ---")
    with _lock:
        _record_history()

    if want_mail:
        ok, message = mailer.send(snapshot, suite.get("report_route", "/report/"))
        with _lock:
            _state["mail"] = {"ok": ok, "message": message}
            _state["log_lines"].append("--- Email: " + message + " ---")


def audit_options_to_env(options):
    """Translate the dashboard's audit options into the env vars
    test_audit_multi_scope.py reads: AUDIT_ENV_TAG (reuse data built
    earlier; empty = build fresh), AUDIT_HEADED, AUDIT_SEED."""
    options = options or {}
    env = {}
    if options.get("mode") == "reuse" and options.get("env_tag"):
        env["AUDIT_ENV_TAG"] = str(options["env_tag"]).strip()
    # "resume": the suppliers of that run exist, build items onward
    if options.get("mode") == "resume" and options.get("env_tag"):
        env["AUDIT_RESUME_TAG"] = str(options["env_tag"]).strip()
    env["AUDIT_HEADED"] = "1" if options.get("headed") else "0"
    if options.get("seed"):
        env["AUDIT_SEED"] = str(options["seed"]).strip()
    return env


_RE_COLLECTED = re.compile(r"collected (\d+) items?")
_RE_TEST = re.compile(r"(\S+::[A-Za-z0-9_]+)(\[[^\]]*\])? (PASSED|FAILED|ERROR|SKIPPED)")
_RE_TEST_START = re.compile(r"^(\S+::test_\S+)")
# A verdict that lost its test name: pywinauto's UIA calls (the negative
# suite's popup-guard fixture) make Python's faulthandler print "Windows
# fatal exception: code 0x8001010d" plus a stack dump right after
# "file::test_x ", so "PASSED [ 4%]" lands at the start of a later line.
_RE_BARE_VERDICT = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED)\s")
_RE_FAIL_HDR = re.compile(r"^_+ (?:ERROR at setup of )?(test_\w+(?:\[[^\]]*\])?) _+$")
_RE_ASSERT = re.compile(r"^E\s+(.*)")
_RE_CODE = re.compile(r"created (IAU-\d+)")
_RE_SEED = re.compile(r"SEED=(\d+)")


def _ingest_progress(line, suite):
    """Update the live counters from one log line. Cheap regexes only -
    this runs on every line while a suite streams."""
    st = _state
    m = _RE_COLLECTED.search(line)
    if m:
        st["tests_total"] += int(m.group(1))     # += : a multi-stage suite collects more than once
    m = _RE_TEST.search(line)
    if m:
        name, param, verdict = m.group(1), m.group(2) or "", m.group(3)
        key = {"PASSED": "passed", "FAILED": "failed", "ERROR": "errors", "SKIPPED": "skipped"}[verdict]
        st[key] += 1
        st["current_test"] = name.split("::")[-1]
        short = name.split("::")[-1]
        st["tests"].append({"name": short + param, "status": verdict})
        st["_open_test"] = None
    else:
        m = _RE_TEST_START.match(line)
        if m:
            st["current_test"] = m.group(1).split("::")[-1]
            st["_open_test"] = st["current_test"]
        else:
            m = _RE_BARE_VERDICT.match(line)
            # "::" check: the end-of-run summary ("FAILED file::test - msg")
            # also starts with a verdict word and must not be counted twice
            if m and st.get("_open_test") and "::" not in line:
                verdict = m.group(1)
                key = {"PASSED": "passed", "FAILED": "failed", "ERROR": "errors", "SKIPPED": "skipped"}[verdict]
                st[key] += 1
                st["tests"].append({"name": st["_open_test"], "status": verdict})
                st["_open_test"] = None
    m = _RE_FAIL_HDR.match(line)
    if m:
        st["_pending_failure"] = m.group(1)
    m = _RE_ASSERT.match(line)
    if m and st.get("_pending_failure"):
        st["failures"].append({"test": st["_pending_failure"], "reason": m.group(1)[:300]})
        base = st["_pending_failure"].split("[")[0]
        for t in st["tests"]:
            if t["name"].split("[")[0] == base and not t.get("reason"):
                t["reason"] = m.group(1)[:300]
        st["_pending_failure"] = None
    if suite.get("counts_sales"):
        _ingest_sale_line(line)
    m = _RE_CODE.search(line)
    if m:
        st["audit_code"] = m.group(1)
    m = _RE_SEED.search(line)
    if m and not st["seed"]:
        st["seed"] = m.group(1)
    if suite.get("has_options"):
        _advance_audit_steps(line)


_RE_SALE_START = re.compile(r"--- SALE (\d+) / (\d+)\s+customer=(\S+) ---")
_RE_SALE_END = re.compile(r"^\s*SALE (\d+) (OK|SHORT|FAIL)(?![A-Za-z]):?\s*(.*)")


def _ingest_sale_line(line):
    """Load test (a plain script, not pytest): one sale = one 'test', so
    the tiles show N sales passed / failed instead of staying at 0. Reads
    load_test.py's own log lines - the script itself is not touched."""
    st = _state
    m = _RE_SALE_START.search(line)
    if m:
        st["tests_total"] = int(m.group(2))
        st["current_test"] = "sale %s - %s" % (m.group(1), m.group(3))
        return
    m = _RE_SALE_END.match(line)
    if not m:
        return
    name = st.get("current_test") or ("sale " + m.group(1))
    if m.group(2) == "OK":
        st["passed"] += 1
        st["tests"].append({"name": name, "status": "PASSED"})
    else:
        reason = (m.group(2) + " " + m.group(3)).strip()[:300]
        st["failed"] += 1
        st["tests"].append({"name": name, "status": "FAILED", "reason": reason})
        st["failures"].append({"test": name, "reason": reason})


def _advance_audit_steps(line):
    steps = _state["audit_steps"]
    if not steps:
        _state["audit_steps"] = steps = [{"key": k, "label": l, "state": "pending"} for k, l, _ in AUDIT_STEPS]
    hit = None
    for i, (k, l, rx) in enumerate(AUDIT_STEPS):
        if rx.search(line):
            hit = i
    if hit is None:
        return
    for i, step in enumerate(steps):
        if i < hit:
            step["state"] = "done"
        elif i == hit:
            step["state"] = "active"
    # detail for the items step: "env: item 16 ..." -> progress text
    m = re.search(r"env: item\s+(\d+)", line)
    if m:
        steps[1]["detail"] = "item %s" % m.group(1)
    m = re.search(r"scan (\S+)\s+expected=(\w+)\s+accepted=(\w+)", line)
    if m:
        steps[5]["detail"] = "%s %s" % (m.group(1), "accepted" if m.group(3) == "True" else "refused")


def _finish_audit_steps(exit_code, stopped):
    for step in _state["audit_steps"]:
        if step["state"] == "active":
            step["state"] = "stopped" if stopped else ("done" if step["key"] != "verify" or exit_code == 0 else "failed")
    if _state["audit_steps"] and not stopped:
        _state["audit_steps"][-1]["state"] = "done" if exit_code == 0 else "failed"


def _tests_from_allure(results_path):
    """The exact test titles Allure shows (allure.dynamic.title) with their
    status, in execution order - so the PDF and the mail list the very
    same names and serial numbers as the Allure report. Falls back to the
    log-parsed list when the results folder has nothing usable."""
    out = []
    try:
        for fn in os.listdir(results_path):
            if not fn.endswith("-result.json"):
                continue
            with open(os.path.join(results_path, fn), encoding="utf-8") as f:
                r = json.load(f)
            status = (r.get("status") or "").upper()
            status = {"PASSED": "PASSED", "FAILED": "FAILED", "BROKEN": "ERROR", "SKIPPED": "SKIPPED"}.get(status, status)
            reason = ""
            sd = r.get("statusDetails") or {}
            if status != "PASSED" and sd.get("message"):
                # header line plus the first few detail lines - for the
                # mismatch checks the header alone ("... has mismatches:")
                # says nothing about WHAT mismatched
                lines = [l.strip() for l in sd["message"].strip().splitlines() if l.strip()]
                reason = " | ".join(lines[:4])[:400]
            out.append({"name": r.get("name") or r.get("fullName") or fn, "status": status,
                        "reason": reason, "_start": r.get("start") or 0})
    except Exception:
        return []
    out.sort(key=lambda t: t["_start"])
    for t in out:
        t.pop("_start", None)
    return out


def _reset_progress():
    _state.update({"tests_total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                   "current_test": None, "failures": [], "tests": [], "pdf_path": None,
                   "audit_steps": [], "audit_code": None, "seed": None, "_pending_failure": None,
                   "_open_test": None})


def _record_history():
    entry = {k: _state[k] for k in ("suite", "label", "started_at", "finished_at", "exit_code",
                                    "status", "tests_total", "passed", "failed", "errors",
                                    "skipped", "report_route", "audit_code", "seed", "options")}
    entry["failures"] = _state["failures"][:10]
    entry["tests"] = _state["tests"]
    entry["pdf_path"] = _state.get("pdf_path")
    entry["duration"] = (_state["finished_at"] or 0) - (_state["started_at"] or 0)
    history = load_history()
    history.insert(0, entry)
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[:HISTORY_LIMIT], f, indent=1, default=str)
    except Exception:
        pass


def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def clear_history():
    try:
        os.remove(HISTORY_FILE)
    except Exception:
        pass


SESSION_STARTED_AT = time.time()


def last_results():
    """{suite_key: last entry} for the suite cards - ONLY runs from this
    dashboard session. Reopening the console starts every card fresh
    ("never run"); the full history table still keeps everything."""
    out = {}
    for e in load_history():
        if (e.get("started_at") or 0) < SESSION_STARTED_AT:
            continue
        if e.get("suite") not in out:
            out[e["suite"]] = e
    return out


def reset_state():
    """Back to the initial state (the Reset button). Refuses while a
    suite is running - the live run must not lose its status mid-way."""
    global SESSION_STARTED_AT
    with _lock:
        if _state["status"] == "running":
            return False, "A suite is running - stop it first."
        _state.update({"status": "idle", "suite": None, "label": None, "log_lines": [],
                       "exit_code": None, "started_at": None, "finished_at": None,
                       "report_ready": False, "report_route": "/report/", "mail": None, "options": {}})
        _reset_progress()
        SESSION_STARTED_AT = time.time()      # cards forget earlier runs too
    # Reset means reset: the run history went with it as far as anyone
    # using the page was concerned, so clear that too rather than leaving
    # yesterday's rows sitting under a console that says "No run yet".
    clear_history()
    return True, "reset"


def start_run(suite_key, options=None):
    if suite_key not in SUITES:
        return False, "Unknown suite: " + suite_key

    with _lock:
        if _state["status"] == "running":
            return False, "A suite is already running (" + str(_state["label"]) + ") - wait for it to finish."
        _state["status"] = "running"
        _state["suite"] = suite_key
        _state["label"] = SUITES[suite_key]["label"]
        _state["log_lines"] = []
        _state["exit_code"] = None
        _state["started_at"] = time.time()
        _state["finished_at"] = None
        _state["report_ready"] = False
        _state["report_route"] = SUITES[suite_key].get("report_route", "/report/")
        if SUITES[suite_key].get("has_options"):
            _state["extra_env"] = audit_options_to_env(options)
        elif SUITES[suite_key].get("group"):
            # the Exe Setup folder carries a back-office picker; setup_tasks.py
            # reads SETUP_ENV as the default for its --env argument
            chosen = (options or {}).get("setup_env") or "demostore"
            _state["extra_env"] = {"SETUP_ENV": str(chosen)}
        else:
            _state["extra_env"] = {}
        _state["options"] = options or {}
        _state["mail"] = None
        _reset_progress()

    thread = threading.Thread(target=_run_in_thread, args=(suite_key,), daemon=True)
    thread.start()
    return True, "Started " + SUITES[suite_key]["label"]


def stop_run():
    global _stop_requested
    with _lock:
        if _state["status"] != "running" or _current_process is None:
            return False, "Nothing is running."
        pid = _current_process.pid
        _stop_requested = True

    # taskkill /T kills the whole process tree (pytest + whatever it
    # spawned - pywinauto driving the exe, or a Playwright browser),
    # not just the top pytest process.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
    with _lock:
        _state["log_lines"].append("--- Stop requested, killing process tree (PID " + str(pid) + ") ---")
    return True, "Stopping…"
