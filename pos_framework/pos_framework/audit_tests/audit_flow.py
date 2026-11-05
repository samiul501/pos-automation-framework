# ============================================================
# AUDIT FLOW - the whole supplier-wise audit chain, end to end,
# driven entirely by data picked live from the database:
#
#   pick scenario -> web: create setup + approve
#                 -> exe: select code, scan, Fn+F1
#                 -> db : what actually synced
#                 -> web: Audit Summary Report, compared to expected
#
# Nothing about the supplier, category, items, or even the audit
# description is fixed: every run gets a fresh random pick and a
# unique tag, so the suite can never pass on stale luck. The seed
# is recorded so any run can be replayed exactly:
#
#   python -m audit_tests.audit_flow              # fresh data
#   python -m audit_tests.audit_flow --seed 1234  # replay
#   python -m audit_tests.audit_flow --headed     # watch the browser
#
# This module only RUNS the flow and records what happened. The
# assertions live in test_audit_supplier_scope.py, so a failing
# expectation never stops the rest of the evidence being collected.
# ============================================================

import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pos_helpers as h
import pos_actions as a

from audit_tests import audit_actions as aa
from audit_tests import audit_config as acfg
from audit_tests import audit_db as adb
from audit_tests import audit_env as aenv
from audit_tests import audit_web as aw

from playwright.sync_api import sync_playwright

OFFICE_NAME = "Dhanmondi Outlet"     # OfficeId 9  = acfg.AUDIT_OFFICE_ID
WAREHOUSE_NAME = "DISPLAY"           # WarehouseId 16 = acfg.AUDIT_WAREHOUSE_ID


def _log(msg):
    print("[audit_flow] " + msg, flush=True)


# ---- step 1: web setup + approval ----------------------------------

def create_and_approve(scenario, headed=False, screenshots_dir=None):
    """Create the audit setup for `scenario` and approve it. Returns the
    audit code and the DB rows that prove both happened."""
    today = datetime.date.today().isoformat()
    before = adb.get_latest_audit_setup()

    with sync_playwright() as p:
        browser, page = aw.login(p, headless=not headed)
        try:
            aw.open_create_audit(page)
            aw.fill_audit_header(page, OFFICE_NAME, WAREHOUSE_NAME, today, today,
                                 scenario["description"])
            aw.add_scope_row(page,
                             supplier_search=scenario["supplier_name"],
                             supplier_option=scenario["supplier_name"],
                             category_name=scenario["category_name"],
                             sub_category_name=scenario["sub_category_name"])
            staged = aw.scope_grid_rows(page)
            if screenshots_dir:
                aw.screenshot(page, os.path.join(screenshots_dir, "01_scope_staged.png"))
            if not staged:
                raise AssertionError("scope row was not staged in the grid - nothing to save")
            aw.save_audit(page)

            created = adb.get_latest_audit_setup()
            if before and created["AuditSetupId"] == before["AuditSetupId"]:
                raise AssertionError("no new audit setup appeared after SAVE (toasts: %r)"
                                     % aw.toast_messages(page))
            code = created["strAuditSetupCode"]
            _log("created %s (AuditSetupId %s), pending=%s"
                 % (code, created["AuditSetupId"], not created["isApprove"]))

            aw.open_audit_config_approval(page)
            queue = aw.approval_queue_rows(page)
            aw.approve_audit_setup(page, code)
            if screenshots_dir:
                aw.screenshot(page, os.path.join(screenshots_dir, "02_after_approve.png"))
        finally:
            browser.close()

    setup = adb.get_audit_setup(code)
    scope = adb.get_audit_scope(setup["AuditSetupId"])
    _log("approved=%s, scope=%s" % (setup["isApprove"],
         [(r["intSupplierId"], r["intCategoryId"], r["intSubCategoryId"]) for r in scope]))
    return {
        "code": code,
        "setup_before_approve": created,
        "setup": setup,
        "scope": scope,
        "staged_grid": staged,
        "approval_queue": queue,
    }


# ---- step 2: exe scan + sync ---------------------------------------

def scan_and_sync(code, plan, launch=True):
    """Drive the exe through the scan plan and force the sync. Returns
    per-barcode outcomes plus the sync popup."""
    if launch:
        h.launch_app()
        a.do_login()
    main = h.get_main_window()
    aa.open_audit_screen(main)
    offered = aa.select_audit_code(main, code)
    _log("audit codes offered by exe: %s" % offered)

    outcomes = []
    for barcode, expected in plan:
        before, after = aa.scan_barcode(main, barcode, settle=1.5)
        popup = aa.detect_popup(main, timeout=2.2)
        if popup:
            aa.dismiss_popup(main)
            time.sleep(0.5)
        outcome = {
            "barcode": barcode,
            "expected": expected,
            "accepted": after > before,
            "popup": popup["text"] if popup else None,
        }
        outcomes.append(outcome)
        _log("scan %-14s expected=%-16s accepted=%-5s popup=%s"
             % (barcode, expected, outcome["accepted"], outcome["popup"]))

    grid = aa.grid_rows(main)
    sync_popup = aa.force_sync(main, settle=8, dismiss=True)
    _log("sync popup: %s" % (sync_popup["text"] if sync_popup else None))

    try:
        a.do_logout(main)
    except Exception as e:      # logout is best-effort; the data is already synced
        _log("logout warning: %s" % str(e)[:80])
    try:
        a.close_app(main)
    except Exception as e:
        _log("close warning: %s" % str(e)[:80])

    return {"outcomes": outcomes, "grid": grid,
            "sync_popup": sync_popup["text"] if sync_popup else None}


# ---- step 3: report ------------------------------------------------

def read_reports(code, supplier_name, headed=False, screenshots_dir=None):
    """The Audit Summary Report for the chosen supplier and for All."""
    with sync_playwright() as p:
        browser, page = aw.login(p, headless=not headed)
        try:
            aw.open_audit_summary_report(page)
            by_supplier = aw.run_audit_summary(page, code, based_on="Supplier",
                                               supplier_name=supplier_name)
            if screenshots_dir:
                aw.screenshot(page, os.path.join(screenshots_dir, "03_report_supplier.png"))
            all_suppliers = aw.run_audit_summary(page, code, based_on="Supplier",
                                                 supplier_name="All")
            if screenshots_dir:
                aw.screenshot(page, os.path.join(screenshots_dir, "04_report_all.png"))
        finally:
            browser.close()
    return {"by_supplier": by_supplier, "all_suppliers": all_suppliers}


# ---- the whole thing -----------------------------------------------

def build_env(seed=None, headed=True, suppliers=None, items_per_supplier=None):
    """Create suppliers, items and stock for this run through the web UI
    (see audit_env). Headed by default - the operator asked to watch."""
    with sync_playwright() as p:
        browser, page = aenv.login_maximized(p, headed=headed)
        try:
            return aenv.build_environment(page, seed=seed, suppliers=suppliers,
                                          items_per_supplier=items_per_supplier, log=_log)
        finally:
            browser.close()


def run_full_flow(seed=None, headed=False, in_scope_items=3, repeats=1,
                  screenshots_dir=None, results_path=None, build_environment=True,
                  suppliers=None, items_per_supplier=None):
    if not adb.db.is_available():
        raise RuntimeError("database not reachable: " + str(adb.db.unavailable_reason())[:160])

    env = None
    if build_environment:
        env = build_env(seed=seed, headed=headed, suppliers=suppliers,
                        items_per_supplier=items_per_supplier)
        scenario = adb.scenario_from_env(env, seed=seed, in_scope_items=in_scope_items,
                                         repeats=repeats)
    else:
        scenario = adb.pick_supplier_scope_scenario(seed=seed, in_scope_items=in_scope_items,
                                                    repeats=repeats)
    plan = adb.scan_plan(scenario, seed=seed)
    _log("SEED=%r TAG=%s" % (seed, scenario["tag"]))
    _log("scope: supplier %s %r + category %s %r / sub %s %r"
         % (scenario["supplier_id"], scenario["supplier_name"],
            scenario["category_id"], scenario["category_name"],
            scenario["sub_category_id"], scenario["sub_category_name"]))
    _log("plan: %s" % plan)

    result = {"seed": seed, "scenario": _jsonable(scenario), "plan": plan,
              "environment": _jsonable(env) if env else None}
    result["setup"] = _jsonable(create_and_approve(scenario, headed, screenshots_dir))
    code = result["setup"]["code"]
    result["scan"] = scan_and_sync(code, plan)

    time.sleep(2)
    result["db_rows"] = _jsonable(adb.get_scan_rows(code))
    result["expected_supplier"] = _jsonable(
        adb.expected_report_totals(code, supplier_id=scenario["supplier_id"]))
    result["expected_all"] = _jsonable(adb.expected_report_totals(code))
    result["reports"] = read_reports(code, scenario["supplier_name"], headed, screenshots_dir)

    if results_path:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, default=str)
        _log("results -> " + results_path)
    return result


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="One-session audit run: [build env] -> setup -> approve -> exe -> report")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--env-tag", default=None, help="reuse suppliers/items built earlier (AUTO-SUP-<tag>-n)")
    ap.add_argument("--suppliers", type=int, default=None)
    ap.add_argument("--items-per-supplier", type=int, default=None)
    ap.add_argument("--resume-tag", default=None, help="suppliers already exist with this tag - start at item profile")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else int(time.time()) % 100000
    r = run_single_session(seed=seed, headed=args.headed, env_tag=args.env_tag,
                           suppliers=args.suppliers, items_per_supplier=args.items_per_supplier,
                           results_path=args.out, resume_tag=args.resume_tag)
    print("\nDONE. seed=%s code=%s" % (seed, r["setup"]["code"]))


# ---- multi-scope audit on an existing environment -------------------

def create_multi_scope_and_approve(scenario, headed=False):
    today = datetime.date.today().isoformat()
    before = adb.get_latest_audit_setup()
    with sync_playwright() as p:
        browser, page = aw.login(p, headless=not headed)
        try:
            aw.open_create_audit(page)
            aw.fill_audit_header(page, OFFICE_NAME, WAREHOUSE_NAME, today, today,
                                 scenario["description"])
            for r in scenario["rows"]:
                aw.add_scope_row(page, supplier_search=r["supplier_name"],
                                 supplier_option=r["supplier_name"],
                                 category_name=r["category_name"],
                                 sub_category_name=r["sub_category_name"])
                _log("scope row staged: %s + %s" % (r["supplier_name"], r["category_name"]))
            staged = aw.scope_grid_rows(page)
            if len(staged) != len(scenario["rows"]):
                raise AssertionError("staged %d rows, expected %d: %s" % (len(staged), len(scenario["rows"]), staged))
            aw.save_audit(page)
            created = adb.get_latest_audit_setup()
            if before and created["AuditSetupId"] == before["AuditSetupId"]:
                raise AssertionError("no new audit setup after SAVE (toasts %r)" % aw.toast_messages(page))
            code = created["strAuditSetupCode"]
            _log("created %s (AuditSetupId %s), pending=%s" % (code, created["AuditSetupId"], not created["isApprove"]))
            aw.open_audit_config_approval(page)
            queue = aw.approval_queue_rows(page)
            aw.approve_audit_setup(page, code)
        finally:
            browser.close()
    setup = adb.get_audit_setup(code)
    scope = adb.get_audit_scope(setup["AuditSetupId"])
    _log("approved=%s, scope rows in DB=%d" % (setup["isApprove"], len(scope)))
    return {"code": code, "setup_before_approve": created, "setup": setup, "scope": scope,
            "staged_grid": staged, "approval_queue": queue}


def read_reports_multi(code, supplier_names, headed=False):
    out = {}
    with sync_playwright() as p:
        browser, page = aw.login(p, headless=not headed)
        try:
            aw.open_audit_summary_report(page)
            for name in supplier_names:
                out[name] = aw.run_audit_summary(page, code, based_on="Supplier", supplier_name=name)
                _log("report %s: %d rows, no_data=%s" % (name, len(out[name]["rows"]), out[name]["no_data"]))
            out["All"] = aw.run_audit_summary(page, code, based_on="Supplier", supplier_name="All")
            _log("report All: %d rows, no_data=%s" % (len(out["All"]["rows"]), out["All"]["no_data"]))
        finally:
            browser.close()
    return out


def run_multi_scope(tag, seed=None, headed=False, results_path=None):
    """Audit with one scope row per supplier on an environment that was
    already built (audit_env.build_environment / load_environment)."""
    if not adb.db.is_available():
        raise RuntimeError("database not reachable: " + str(adb.db.unavailable_reason())[:160])
    env = aenv.load_environment(tag)
    scenario = adb.multi_scope_scenario(env, seed=seed)
    _log("SEED=%r TAG=%s rows=%s" % (seed, scenario["tag"],
         [(r["supplier_name"], r["category_name"]) for r in scenario["rows"]]))
    _log("plan: %d accept + %d reject probes" % (len(scenario["accept"]), len(scenario["probes"])))

    result = {"seed": seed, "environment": _jsonable(env), "scenario": _jsonable(scenario),
              "plan": scenario["plan"]}
    result["setup"] = _jsonable(create_multi_scope_and_approve(scenario, headed))
    code = result["setup"]["code"]
    result["scan"] = scan_and_sync(code, scenario["plan"])
    time.sleep(2)
    result["db_rows"] = _jsonable(adb.get_scan_rows(code))
    result["expected"] = {}
    for r in scenario["rows"]:
        result["expected"][r["supplier_name"]] = _jsonable(
            adb.expected_report_totals(code, supplier_id=r["supplier_id"]))
    result["expected"]["All"] = _jsonable(adb.expected_report_totals(code))
    result["reports"] = read_reports_multi(code, [r["supplier_name"] for r in scenario["rows"]], headed)
    if results_path:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, default=str)
        _log("results -> " + results_path)
    return result


# ---- single-session orchestration ----------------------------------
# ONE login for the whole thing (the operator's flow): the maximized
# browser opened for the environment build stays open through audit
# setup, approval, the exe scan and the report. Nothing re-logs in.

def _setup_and_approve_on(page, scenario):
    today = datetime.date.today().isoformat()
    before = adb.get_latest_audit_setup()
    aw.open_create_audit_in_session(page)
    aw.fill_audit_header(page, OFFICE_NAME, WAREHOUSE_NAME, today, today, scenario["description"])
    for r in scenario["rows"]:
        aw.add_scope_row(page, supplier_search=r["supplier_name"], supplier_option=r["supplier_name"],
                         category_name=r["category_name"], sub_category_name=r["sub_category_name"])
        _log("scope row staged: %s + %s / %s" % (r["supplier_name"], r["category_name"], r["sub_category_name"]))
    staged = aw.scope_grid_rows(page)
    if len(staged) != len(scenario["rows"]):
        raise AssertionError("staged %d rows, expected %d: %s" % (len(staged), len(scenario["rows"]), staged))
    aw.save_audit(page)
    created = adb.get_latest_audit_setup()
    if before and created["AuditSetupId"] == before["AuditSetupId"]:
        raise AssertionError("no new audit setup after SAVE (toasts %r)" % aw.toast_messages(page))
    code = created["strAuditSetupCode"]
    _log("created %s (AuditSetupId %s), pending=%s" % (code, created["AuditSetupId"], not created["isApprove"]))
    aw.open_audit_config_approval_in_session(page)
    queue = aw.approval_queue_rows(page)
    aw.approve_audit_setup(page, code)
    setup = adb.get_audit_setup(code)
    scope = adb.get_audit_scope(setup["AuditSetupId"])
    _log("approved=%s, scope rows in DB=%d" % (setup["isApprove"], len(scope)))
    return {"code": code, "setup_before_approve": created, "setup": setup, "scope": scope,
            "staged_grid": staged, "approval_queue": queue}


def _reports_on(page, code, supplier_names):
    """Audit Summary Report: audit id -> each supplier used in the audit,
    Based On (2) = All Items, Is Details on. Only the suppliers the audit
    was set up with are queried - the operator's instruction."""
    out = {}
    aw.open_audit_summary_report_in_session(page)
    for name in supplier_names:
        out[name] = aw.run_audit_summary(page, code, based_on="Supplier", supplier_name=name,
                                         based_on2="All Items", filter_by="Counted Items", details=True)
        _log("report %s: %d rows, no_data=%s" % (name, len(out[name]["rows"]), out[name]["no_data"]))
    return out


def run_single_session(seed=None, headed=True, env_tag=None, suppliers=None,
                       items_per_supplier=None, results_path=None, resume_tag=None):
    """Everything in one browser session:
         [build env] -> audit setup (multi-scope) -> approve -> exe scan
         -> Fn+F1 -> DB -> report (per supplier) - then close."""
    if not adb.db.is_available():
        raise RuntimeError("database not reachable: " + str(adb.db.unavailable_reason())[:160])
    with sync_playwright() as p:
        browser, page = aenv.login_maximized(p, headed=headed)
        try:
            if env_tag:
                env = aenv.load_environment(env_tag)
                _log("env loaded: tag=%s suppliers=%d items=%d" % (env_tag, len(env["suppliers"]), len(env["items"])))
            else:
                env = aenv.build_environment(page, seed=seed, suppliers=suppliers,
                                             items_per_supplier=items_per_supplier, log=_log,
                                             existing_tag=resume_tag)
            scenario = adb.multi_scope_scenario(env, seed=seed)
            _log("SEED=%r TAG=%s rows=%s" % (seed, scenario["tag"],
                 [(r["supplier_name"], r["category_name"]) for r in scenario["rows"]]))
            result = {"seed": seed, "environment": _jsonable(env), "scenario": _jsonable(scenario),
                      "plan": scenario["plan"]}
            result["setup"] = _jsonable(_setup_and_approve_on(page, scenario))
            code = result["setup"]["code"]

            # exe part - the browser simply stays open meanwhile
            result["scan"] = scan_and_sync(code, scenario["plan"])
            time.sleep(2)
            result["db_rows"] = _jsonable(adb.get_scan_rows(code))
            names = [r["supplier_name"] for r in scenario["rows"]]
            result["expected"] = {n: _jsonable(adb.expected_report_totals(code, supplier_id=r["supplier_id"]))
                                  for n, r in zip(names, scenario["rows"])}
            result["reports"] = _reports_on(page, code, names)
        finally:
            browser.close()
    if results_path:
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, default=str)
        _log("results -> " + results_path)
    return result
