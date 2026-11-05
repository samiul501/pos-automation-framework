# ============================================================
# BACK OFFICE CATALOG - what the back-office suite contains, per
# environment, and how each test last did.
#
# WHY THIS IS DISCOVERED AND NOT LISTED
# -------------------------------------
# A hardcoded list of tests goes stale the first time someone adds
# one, and then the dashboard quietly lies. So nothing here names a
# test: the tree is read from the source every time it changes.
#
#   environments  <- the framework's own profile registry, so a new
#                    profiles/<app>.py appears in the UI by itself
#   modules       <- the folders under backoffice/tests
#   tests         <- parsed out of those files with ast, which also
#                    yields the docstring, the markers and the
#                    allure feature/story a test declares
#
# ast rather than `pytest --collect-only`: it needs no subprocess,
# it cannot be broken by an import error in an unrelated module,
# and it gives the human-readable title that collection does not.
#
# NAMED backoffice_catalog AND NOT backoffice: the dashboard folder is
# on sys.path, so a module called backoffice here would shadow the
# framework's own backoffice PACKAGE and the profile import below would
# resolve to this file instead.
#
# HOW A TEST'S STATUS IS KNOWN
# ----------------------------
# From the last run's Allure results for THAT environment - real
# evidence, not a prediction. A test that has never run says so.
# A skipped one carries its reason, which for this suite names the
# exact profile keys still missing.
# ============================================================

import ast
import json
import os
import re
import subprocess
import sys
import time

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
POS_FRAMEWORK_DIR = os.path.join(os.path.dirname(DASHBOARD_DIR), "pos_framework")
BACKOFFICE_DIR = os.path.join(POS_FRAMEWORK_DIR, "backoffice")
TESTS_DIR = os.path.join(BACKOFFICE_DIR, "tests")
RESULTS_ROOT = os.path.join(os.path.dirname(DASHBOARD_DIR), "reports")

# A module's folder name is not what a person calls it.
MODULE_LABELS = {
    "": "Harness",
    "configuration": "Configuration",
    "purchase": "Purchase",
    "sales": "Sales",
    "inventory": "Inventory",
    "accounts": "Accounts",
    "payroll": "Payroll",
    "pos": "POS",
}


# ---- environments ---------------------------------------------------

def _load_env_once():
    """The credentials live in the framework's .env, which only its own
    conftest reads. Without this the dashboard would report every
    environment as having no credentials."""
    path = os.path.join(POS_FRAMEWORK_DIR, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
    except OSError:
        pass


def apps():
    """The environments the framework knows, straight from its own
    profile registry - so adding profiles/<new>.py is all it takes for a
    new suite tile to appear here."""
    if POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, POS_FRAMEWORK_DIR)
    _load_env_once()
    try:
        from backoffice.profiles import registry
    except Exception as e:
        return [], str(e)[:200]

    out = []
    for key in registry.names():
        profile = registry.get(key)
        out.append({
            "key": key,
            "label": profile.label or key,
            "base_url": profile.base_url,
            "database": profile.database,
            "screens": sorted(profile.nav),
            "forms": sorted(profile.forms),
            "flags": dict(profile.flags),
            "has_credentials": bool(profile.username() and profile.password()),
            # Relative to pos_framework/pos_framework, which is where the
            # runner starts pytest and where `allure generate` runs.
            "results_dir": "../reports/allure-results-backoffice-" + key,
            "report_dir": "../reports/allure-report-backoffice-" + key,
            "report_route": "/report-backoffice-" + key + "/",
        })
    return out, None


def app(key):
    found, _ = apps()
    for a in found:
        if a["key"] == key:
            return a
    return None


# ---- the test tree, parsed from source ------------------------------

_CACHE = {"stamp": None, "modules": None}


def _source_stamp():
    """Newest mtime under the tests folder - the cache key. Cheap enough
    to do on every request and exact enough that a saved file shows up
    immediately."""
    newest = 0.0
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    pass
    return newest


def _marker_names(decorators):
    """pytest.mark.<name> off a decorator list."""
    names = []
    for node in decorators:
        target = node.func if isinstance(node, ast.Call) else node
        parts = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        parts.reverse()
        if len(parts) >= 3 and parts[0] == "pytest" and parts[1] == "mark":
            names.append(parts[2])
    return names


def _allure_labels(decorators):
    """@allure.feature("...") / @allure.story("...") if present."""
    out = {}
    for node in decorators:
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == "allure" and node.args):
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out[target.attr] = arg.value
    return out


def _file_level_markers(tree):
    """pytestmark = pytest.mark.module (and the list form)."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        value = node.value
        items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        return _marker_names(items)
    return []


def _title_from(name, docstring):
    """The first line of the docstring is written for a person; the
    function name is the fallback."""
    if docstring:
        first = docstring.strip().splitlines()[0].strip()
        if first:
            return first
    return name.replace("test_", "").replace("_", " ").strip().capitalize()


def _parse_file(path, module_key):
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError) as e:
        return [], str(e)[:200]

    file_markers = _file_level_markers(tree)
    rel = os.path.relpath(path, TESTS_DIR).replace("\\", "/")
    tests = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        labels = _allure_labels(node.decorator_list)
        tests.append({
            "id": rel + "::" + node.name,
            "name": node.name,
            "title": _title_from(node.name, ast.get_docstring(node)),
            "description": (ast.get_docstring(node) or "").strip(),
            "file": rel,
            "module": module_key,
            "markers": sorted(set(file_markers + _marker_names(node.decorator_list))),
            "feature": labels.get("feature"),
            "story": labels.get("story"),
            "line": node.lineno,
        })
    return tests, None


def modules(force=False):
    """The test tree: a list of modules, each with its tests.

    Grouped by the folder under tests/ - which is the module the QA
    team means when they say "the sales module", so a new folder is a
    new section in the UI with nothing else to change.
    """
    stamp = _source_stamp()
    if not force and _CACHE["stamp"] == stamp and _CACHE["modules"] is not None:
        return _CACHE["modules"]

    found = {}
    problems = []
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        module_key = os.path.relpath(root, TESTS_DIR).replace("\\", "/")
        if module_key == ".":
            module_key = ""
        for name in sorted(files):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            tests, error = _parse_file(os.path.join(root, name), module_key)
            if error:
                problems.append(name + ": " + error)
            if tests:
                found.setdefault(module_key, []).extend(tests)

    out = []
    for key in sorted(found, key=lambda k: (k != "", k)):
        tests = sorted(found[key], key=lambda t: (t["file"], t["line"]))
        out.append({
            "key": key or "harness",
            "label": MODULE_LABELS.get(key, key.replace("_", " ").title() or "Harness"),
            "path": "tests/" + key if key else "tests",
            "tests": tests,
            "count": len(tests),
            "problems": problems if key == "" else [],
        })

    _CACHE["stamp"] = stamp
    _CACHE["modules"] = out
    return out


# ---- the scenarios inside a test --------------------------------------

_VARIANTS = {"stamp": None, "app": None, "value": None}

VENV_PYTHON = os.path.join(os.path.dirname(DASHBOARD_DIR), "venv", "Scripts", "python.exe")


def _variants(app_key, stamp):
    """Which parametrised cases each test actually has.

    Asked of pytest rather than worked out from the source: a
    parametrize list built from a variable (SCENARIOS, a list
    comprehension) cannot be read off the syntax tree, and guessing
    would put scenarios on the page that do not exist.

    One collection per app, cached until a test file changes. Collection
    imports nothing heavy and takes well under a second.
    """
    if (_VARIANTS["stamp"], _VARIANTS["app"]) == (stamp, app_key) and _VARIANTS["value"]:
        return _VARIANTS["value"]

    found = {}
    try:
        result = subprocess.run(
            [VENV_PYTHON, "-m", "pytest", "backoffice", "-c", "backoffice/pytest.ini",
             "--app", app_key, "-p", "no:cacheprovider", "-q", "--collect-only"],
            cwd=POS_FRAMEWORK_DIR, capture_output=True, text=True, timeout=120,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        lines = (result.stdout or "").splitlines()
    except Exception:
        lines = []

    for line in lines:
        line = line.strip()
        if "::" not in line or not line.startswith("tests/"):
            continue
        path, _, rest = line.partition("::")
        match = re.match(r"^([A-Za-z0-9_]+)(?:\[(.+)\])?$", rest)
        if not match:
            continue
        function, params = match.group(1), match.group(2)
        if not params:
            continue
        # "chromium-heavy" -> "heavy". The browser is not a scenario, and
        # neither is the bare True/False of a boolean parameter that sits
        # beside a readable label.
        label = re.sub(r"^(chromium|firefox|webkit)-?", "", params)
        label = re.sub(r"^(True|False)-(?=\S)", "", label).strip()
        if not label:
            continue
        key = path[len("tests/"):] + "::" + function
        found.setdefault(key, []).append({
            "label": label,
            # the target a run uses, relative to backoffice/tests
            "target": path[len("tests/"):] + "::" + function + "[" + params + "]",
        })

    _VARIANTS.update({"stamp": stamp, "app": app_key, "value": found})
    return found


# ---- what happened last time ----------------------------------------

def _results_dir(app_key):
    return os.path.join(RESULTS_ROOT, "allure-results-backoffice-" + app_key)


def last_results(app_key):
    """{test function name: how it went} from the last run of this app.

    Allure writes one *-result.json per test. Only the newest is kept per
    test name, because a rerun leaves the older file behind.
    """
    folder = _results_dir(app_key)
    if not os.path.isdir(folder):
        return {}

    out = {}
    for name in os.listdir(folder):
        if not name.endswith("-result.json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue

        # fullName looks like "tests.configuration.test_item_create#test_creates_a_new_item"
        full = data.get("fullName") or ""
        func = full.split("#")[-1] if "#" in full else (data.get("name") or "")
        func = func.split("[")[0].strip()
        if not func:
            continue

        details = data.get("statusDetails") or {}
        record = {
            "status": data.get("status") or "unknown",
            "title": data.get("name") or func,
            "message": (details.get("message") or "").strip(),
            "start": data.get("start"),
            "stop": data.get("stop"),
            "duration_ms": (data.get("stop") or 0) - (data.get("start") or 0),
        }
        previous = out.get(func)
        if previous is None or (record["start"] or 0) >= (previous["start"] or 0):
            out[func] = record
    return out


def _summarise(tests):
    counts = {"passed": 0, "failed": 0, "broken": 0, "skipped": 0, "unknown": 0, "never": 0}
    for t in tests:
        status = (t.get("last") or {}).get("status")
        if not status:
            counts["never"] += 1
        elif status in counts:
            counts[status] += 1
        else:
            counts["unknown"] += 1
    counts["total"] = len(tests)
    return counts


def catalog(app_key):
    """Everything the detail page needs for one environment: the
    environment itself, its modules, each test with how it last did, and
    the totals."""
    environment = app(app_key)
    if environment is None:
        return None

    results = last_results(app_key)
    variants = _variants(app_key, _source_stamp())
    tree = []
    every = []
    newest = 0
    for module in modules():
        tests = []
        for test in module["tests"]:
            enriched = dict(test)
            enriched["last"] = results.get(test["name"])
            enriched["variants"] = variants.get(test["id"], [])
            if enriched["last"] and enriched["last"].get("stop"):
                newest = max(newest, enriched["last"]["stop"])
            tests.append(enriched)
            every.append(enriched)
        entry = dict(module)
        entry["tests"] = tests
        entry["summary"] = _summarise(tests)
        tree.append(entry)

    return {
        "app": environment,
        "modules": tree,
        "summary": _summarise(every),
        "last_run_at": newest / 1000.0 if newest else None,
        "has_report": os.path.exists(os.path.join(
            RESULTS_ROOT, "allure-report-backoffice-" + app_key, "index.html")),
        "generated_at": time.time(),
    }
