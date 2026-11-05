# ============================================================
# SELF CHECK - a fast, offline sanity pass over the framework
# itself. No exe, no browser, no database: it must run in a few
# seconds so it can be run before every suite and after every
# edit.
#
# WHY THIS EXISTS
# ---------------
# On 2026-09-24 a one-line edit to pos_helpers.get_main_window()
# left `return main_win` stranded after a `break`, so the
# function could never return - it waited the full timeout and
# then raised "POSAPP window not found" on a window that was
# right there. The file compiled fine, so nothing caught it; it
# only surfaced as a failed run minutes later.
#
# Every check below is aimed at that class of failure - the
# damage a change does to code that was already working:
#
#   1. imports       every module still imports (a typo in one
#                    module no longer takes a suite down at run time)
#   2. unreachable   no statement sits after return/break/continue/
#                    raise in the same block - exactly the bug above
#   3. contracts     the functions the suites call still exist with
#                    the arguments they are called with
#   4. settings      config.py and .env still carry what the suites read
#   5. dashboard     every route answers (Flask test client, no server)
#
# Run it directly:      python tools/selfcheck.py
# or as a test:         python -m pytest tools/test_selfcheck.py
# ============================================================

import os
import io
import ast
import sys
import importlib
import traceback

FRAMEWORK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(FRAMEWORK_DIR)
DASHBOARD_DIR = os.path.join(PROJECT_DIR, "dashboard")

for path in (FRAMEWORK_DIR, DASHBOARD_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

# Directories that are test data / reports, not source.
SKIP_DIRS = {"__pycache__", "venv", ".git", "allure-report", "allure-report-web",
             "allure-report-audit", "allure-results", "allure-results-web",
             "allure-results-audit", "allure-results-credit", "allure-results-issues",
             "allure-results-scratch-check", "graphify-out", "openspec", "reports",
             "screenshots", "backups", "POS_5.0.53.0", "docs"}

# Modules that are safe to import without a machine set up: importing must
# not launch anything, connect anywhere, or need a display.
IMPORTABLE = [
    "config", "pos_helpers", "pos_actions", "db_helpers", "web_helpers",
    "negative_tests.negative_config", "negative_tests.negative_actions",
    "audit_tests.audit_config", "audit_tests.audit_db", "audit_tests.audit_web",
    "audit_tests.audit_actions", "audit_tests.audit_flow",
    "credit_tests.credit_config", "credit_tests.credit_db", "credit_tests.credit_data",
    "credit_tests.credit_web", "credit_tests.credit_actions",
    "client_issues.issue_config", "client_issues.issue_helpers",
]

# What the suites actually call. (module, function, minimum arg count the
# callers rely on). A rename or a dropped parameter shows up here instead of
# half way through a 13-minute run.
CONTRACTS = [
    ("pos_helpers", "launch_app", 0),
    ("pos_helpers", "get_main_window", 0),
    ("pos_helpers", "app_window_exists", 0),
    ("pos_helpers", "wait_and_click", 1),
    ("pos_helpers", "wait_until_ready", 1),
    ("pos_helpers", "press_button_robust", 1),
    ("pos_helpers", "dismiss_notification_popup", 1),
    ("pos_actions", "do_login", 0),
    ("pos_actions", "add_customer_and_items", 3),
    ("pos_actions", "do_payment_and_close", 1),
    ("db_helpers", "is_available", 0),
    ("db_helpers", "find_sellable_items", 0),
    ("credit_tests.credit_actions", "sell_on_credit", 3),
    ("credit_tests.credit_actions", "read_collection_cards", 1),
    ("credit_tests.credit_db", "credit_position", 1),
    ("credit_tests.credit_web", "open_create_customer", 1),
]

# config.py keys the suites read. Missing one is a run-time crash today.
REQUIRED_CONFIG = ["APP_NAME", "APP_ID", "USER_ID", "PASSWORD", "TRANSACTIONS",
                   "WEB_BASE_URL", "WEB_MOBILE", "WEB_PASSWORD", "WEB_VERIFY_DATA_FILE"]

REQUIRED_ENV = ["POS_USER_ID", "POS_PASSWORD", "WEB_MOBILE", "WEB_PASSWORD",
                "DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD"]


class Result(object):
    def __init__(self):
        self.problems = []
        self.notes = []

    def fail(self, area, message):
        self.problems.append((area, message))

    def note(self, message):
        self.notes.append(message)

    @property
    def ok(self):
        return not self.problems


# ---- 1. every module imports ----------------------------------------

def check_imports(result):
    for name in IMPORTABLE:
        try:
            importlib.import_module(name)
        except Exception as e:
            result.fail("import", name + ": " + str(e).splitlines()[0])
    result.note("imported %d modules" % len(IMPORTABLE))


# ---- 2. unreachable code --------------------------------------------

def _python_files():
    for root, dirs, files in os.walk(FRAMEWORK_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)
    if os.path.isdir(DASHBOARD_DIR):
        for f in os.listdir(DASHBOARD_DIR):
            if f.endswith(".py"):
                yield os.path.join(DASHBOARD_DIR, f)


def _unreachable_in(body):
    """Statements that can never run because the one before them always
    leaves the block. Reports (lineno, after-what)."""
    found = []
    stoppers = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    for i, node in enumerate(body[:-1]):
        if isinstance(node, stoppers):
            nxt = body[i + 1]
            found.append((nxt.lineno, type(node).__name__.lower()))
    return found


def check_unreachable(result):
    scanned = 0
    for path in _python_files():
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=path)
        except SyntaxError as e:
            result.fail("syntax", "%s line %s: %s" % (os.path.relpath(path, PROJECT_DIR), e.lineno, e.msg))
            continue
        scanned += 1
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                body = getattr(node, field, None)
                if isinstance(body, list):
                    for lineno, after in _unreachable_in(body):
                        result.fail("unreachable",
                                    "%s:%d is unreachable (it follows a %s)"
                                    % (os.path.relpath(path, PROJECT_DIR), lineno, after))
    result.note("scanned %d files for unreachable code" % scanned)


# ---- 3. the functions the suites call still exist --------------------

def check_contracts(result):
    import inspect
    for module_name, func_name, min_args in CONTRACTS:
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            result.fail("contract", module_name + " will not import: " + str(e).splitlines()[0])
            continue
        func = getattr(module, func_name, None)
        if func is None:
            result.fail("contract", module_name + "." + func_name + " is gone")
            continue
        try:
            spec = inspect.getfullargspec(func)
        except TypeError:
            continue
        required = len(spec.args) - len(spec.defaults or ())
        if required > min_args:
            result.fail("contract",
                        "%s.%s now needs %d argument(s); callers pass %d"
                        % (module_name, func_name, required, min_args))
    result.note("checked %d call contracts" % len(CONTRACTS))


# ---- 4. settings -----------------------------------------------------

def check_settings(result):
    try:
        import config
    except Exception as e:
        result.fail("config", "config.py will not import: " + str(e))
        return
    for key in REQUIRED_CONFIG:
        if not hasattr(config, key):
            result.fail("config", "config." + key + " is missing")

    env_file = os.path.join(FRAMEWORK_DIR, ".env")
    if not os.path.exists(env_file):
        result.fail("env", ".env is missing (copy .env.example and fill it in)")
        return
    text = io.open(env_file, encoding="utf-8").read()
    for key in REQUIRED_ENV:
        line = [l for l in text.splitlines() if l.strip().startswith(key + "=")]
        if not line:
            result.fail("env", key + " is missing from .env")
        elif not line[0].split("=", 1)[1].strip():
            result.fail("env", key + " is empty in .env")
    result.note("config + .env keys present")


# ---- 5. the dashboard answers ---------------------------------------

def check_dashboard(result):
    if not os.path.isdir(DASHBOARD_DIR):
        result.note("no dashboard directory - skipped")
        return
    try:
        import app as dashboard_app
    except Exception as e:
        result.fail("dashboard", "app.py will not import: " + str(e).splitlines()[0])
        return
    client = dashboard_app.app.test_client()
    for route in ("/", "/api/history", "/api/status", "/api/logs", "/api/mail-status"):
        try:
            response = client.get(route)
        except Exception as e:
            result.fail("dashboard", route + " raised: " + str(e).splitlines()[0])
            continue
        if response.status_code != 200:
            result.fail("dashboard", route + " answered " + str(response.status_code))
    page = client.get("/").get_data(as_text=True)
    for marker in ("suite-card", "exe-group-flag", "exe-inv-select", "brand-mark"):
        if marker not in page:
            result.fail("dashboard", "the page no longer contains " + marker)
    result.note("dashboard routes + page widgets present")


CHECKS = [
    ("imports", check_imports),
    ("unreachable code", check_unreachable),
    ("call contracts", check_contracts),
    ("settings", check_settings),
    ("dashboard", check_dashboard),
]


def run(checks=None):
    result = Result()
    for name, func in (checks or CHECKS):
        try:
            func(result)
        except Exception:
            result.fail(name, "the check itself crashed:\n" + traceback.format_exc())
    return result


def main():
    result = run()
    for note in result.notes:
        print("  ok   " + note)
    if result.ok:
        print("\nSELF CHECK PASSED")
        return 0
    print("")
    for area, message in result.problems:
        print("  FAIL [%s] %s" % (area, message))
    print("\nSELF CHECK FAILED - %d problem(s)" % len(result.problems))
    return 1


if __name__ == "__main__":
    sys.exit(main())
