# ============================================================
# MULTI-SCOPE SUPPLIER AUDIT - one audit, one scope row per
# supplier (each paired with its own category), on an environment
# the suite created itself (audit_env). Runs the whole chain once
# per session, then asserts one thing per test so Allure shows
# exactly which link of the chain broke.
#
#   AUDIT_ENV_TAG=260916164705 pytest audit_tests/test_audit_multi_scope.py \
#       -s -v --alluredir=allure-results-audit
#   allure generate allure-results-audit -o allure-report-audit --clean
#
# AUDIT_ENV_TAG selects an environment already built by
# audit_env.build_environment (suppliers AUTO-SUP-<tag>-n). Without
# it a fresh environment is built first (slow: ~15 min).
# ============================================================

import json
import os
import sys
import time

import allure
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_tests import audit_actions as aa
from audit_tests import audit_flow as flow

TOL = 0.01


def _attach_json(name, obj):
    allure.attach(json.dumps(obj, indent=1, default=str), name, allure.attachment_type.JSON)


@pytest.fixture(scope="module")
def run():
    seed = int(os.environ.get("AUDIT_SEED") or int(time.time()) % 100000)
    headed = os.environ.get("AUDIT_HEADED", "") not in ("", "0")
    tag = os.environ.get("AUDIT_ENV_TAG")
    resume = os.environ.get("AUDIT_RESUME_TAG")      # suppliers exist; build items onward
    here = os.path.dirname(os.path.abspath(__file__))
    with allure.step("One session: [build env] -> setup -> approve -> exe scan -> Fn+F1 -> report (seed %s, env %s)" % (seed, tag or "new")):
        r = flow.run_single_session(seed=seed, headed=headed, env_tag=tag, resume_tag=resume,
                                    results_path=os.path.join(here, "last_multi_%s.json" % seed))
    _attach_json("scenario", r["scenario"])
    _attach_json("scan outcomes", r["scan"])
    _attach_json("db scan rows", r["db_rows"])
    _attach_json("expected (from DB)", r["expected"])
    _attach_json("reports (parsed)", r["reports"])
    return r


# ---- environment ---------------------------------------------------

@allure.feature("Audit environment")
def test_environment_has_stock_for_every_item(run):
    items = run["environment"]["items"]
    no_stock = [i["Barcode"] for i in items if float(i["_stock"]) <= 0]
    assert not no_stock, "items with no stock in the audit warehouse: %s" % no_stock


# ---- setup + approval ---------------------------------------------

@allure.feature("Audit setup")
def test_all_scope_rows_saved_with_suppliers(run):
    want = {(int(r["supplier_id"]), int(r["category_id"]), int(r["sub_category_id"]))
            for r in run["scenario"]["rows"]}
    got = {(int(r["intSupplierId"]), int(r["intCategoryId"]), int(r["intSubCategoryId"]))
           for r in run["setup"]["scope"]}
    assert got == want, (got, want)
    grid_suppliers = {g["supplier"] for g in run["setup"]["staged_grid"]}
    assert grid_suppliers == {r["supplier_name"] for r in run["scenario"]["rows"]}


@allure.feature("Audit setup")
def test_pending_then_approved(run):
    assert run["setup"]["setup_before_approve"]["isApprove"] in (False, 0, "False")
    assert run["setup"]["setup"]["isApprove"] in (True, 1, "True")
    assert run["setup"]["code"] in [q["code"] for q in run["setup"]["approval_queue"]]


# ---- exe ------------------------------------------------------------

def _outcomes(run, expected):
    return [o for o in run["scan"]["outcomes"] if o["expected"] == expected]


@allure.feature("Exe scan")
def test_every_in_scope_item_accepted(run):
    bad = [o for o in _outcomes(run, "accept") if not o["accepted"]]
    assert not bad, "in-scope items refused: %s" % bad


@allure.feature("Exe scan")
def test_items_outside_their_suppliers_category_are_rejected(run):
    """Each probe is an item of a scoped SUPPLIER but in a category that
    supplier is NOT scoped for. Per spec it must be refused."""
    probes = _outcomes(run, "reject_category")
    assert probes, "no probes in plan"
    accepted = [o for o in probes if o["accepted"]]
    assert not accepted, "out-of-scope items ACCEPTED: %s" % [(o["barcode"], o["popup"]) for o in accepted]


@allure.feature("Exe scan")
def test_sync_confirmed(run):
    assert run["scan"]["sync_popup"] and aa.POPUP_SAVED in run["scan"]["sync_popup"].lower(), run["scan"]["sync_popup"]


# ---- database -------------------------------------------------------

@allure.feature("Database")
def test_db_rows_equal_accepted_scans(run):
    accepted = sorted(o["barcode"] for o in run["scan"]["outcomes"] if o["accepted"])
    synced = sorted(r["ItemBarCode"] for r in run["db_rows"])
    assert synced == accepted, (synced, accepted)


# ---- report ---------------------------------------------------------

def _scoped_barcodes(run, supplier_name):
    row = next(r for r in run["scenario"]["rows"] if r["supplier_name"] == supplier_name)
    return {i["Barcode"] for i in run["scenario"]["accept"]
            if int(i["SupplierId"]) == int(row["supplier_id"])}


@allure.feature("Audit Summary Report")
@pytest.mark.parametrize("which", [0, 1, 2])
def test_report_per_supplier_shows_only_its_scoped_items(run, which):
    rows = run["scenario"]["rows"]
    if which >= len(rows):
        pytest.skip("fewer suppliers in this run")
    name = rows[which]["supplier_name"]
    rep = run["reports"][name]
    assert not rep["no_data"], "No Data Found for %s" % name
    shown = {r["barcode"] for r in rep["rows"]}
    assert {r["supplier"] for r in rep["rows"]} == {name}, "foreign supplier rows in %s view" % name
    outside = shown - _scoped_barcodes(run, name)
    assert not outside, "items OUTSIDE %s's scoped category appear in its report: %s" % (name, outside)


@allure.feature("Audit Summary Report")
@pytest.mark.parametrize("which", [0, 1, 2])
def test_report_per_supplier_numbers_match_db(run, which):
    rows = run["scenario"]["rows"]
    if which >= len(rows):
        pytest.skip("fewer suppliers in this run")
    name = rows[which]["supplier_name"]
    rep = {r["barcode"]: r for r in run["reports"][name]["rows"]}
    exp = {r["Barcode"]: r for r in run["expected"][name]["rows"]}
    assert set(rep) == set(exp), (sorted(rep), sorted(exp))
    for bc, e in exp.items():
        r = rep[bc]
        assert abs(r["audit_qty"] - e["counted"]) < TOL, (bc, "audit", r["audit_qty"], e["counted"])
        assert abs(r["system_qty"] - e["systemStock"]) < TOL, (bc, "system", r["system_qty"], e["systemStock"])
        assert abs(r["diff_qty"] - e["variance"]) < TOL, (bc, "diff", r["diff_qty"], e["variance"])
        assert abs(r["diff_cost"] - e["costVariance"]) < TOL, (bc, "cost", r["diff_cost"], e["costVariance"])
        assert abs(r["diff_sale"] - e["salesVariance"]) < TOL, (bc, "sale", r["diff_sale"], e["salesVariance"])
        assert abs(r["diff_qty"] - (r["short_qty"] + r["excess_qty"])) < TOL, bc
    t = run["reports"][name]["total"]
    assert t and abs(t["diff_cost"] - run["expected"][name]["costVariance"]) < TOL
