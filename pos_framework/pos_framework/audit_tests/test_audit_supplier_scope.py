# ============================================================
# SUPPLIER-WISE AUDIT - end-to-end, data-driven.
#
# One full flow runs once per session (setup -> approve -> exe
# scan -> sync -> report) on a supplier/category/item set picked
# live from the database, then each test below asserts one thing
# about what happened. Splitting the assertions means the known
# scan-validation bug does not hide whether the report is right.
#
#   pytest audit_tests/ -s -v
#   AUDIT_SEED=1234 pytest audit_tests/ -s      # replay a run
#   AUDIT_HEADED=1  pytest audit_tests/ -s      # watch the browser
# ============================================================

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit_tests import audit_actions as aa
from audit_tests import audit_flow as flow

TOL = 0.01


@pytest.fixture(scope="module")
def run():
    seed = os.environ.get("AUDIT_SEED")
    seed = int(seed) if seed else int(time.time()) % 100000
    headed = os.environ.get("AUDIT_HEADED", "") not in ("", "0")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "last_run_%s.json" % seed)
    print("\n*** AUDIT_SEED=%s (set this env var to replay) ***" % seed)
    return flow.run_full_flow(seed=seed, headed=headed, results_path=out)


# ---- setup + approval ---------------------------------------------

def test_setup_saved_with_supplier_scope(run):
    s = run["scenario"]
    scope = run["setup"]["scope"]
    assert len(scope) == 1, scope
    assert int(scope[0]["intSupplierId"]) == int(s["supplier_id"])
    assert int(scope[0]["intCategoryId"]) == int(s["category_id"])
    assert int(scope[0]["intSubCategoryId"]) == int(s["sub_category_id"])
    # the UI grid showed the supplier column before save
    assert run["setup"]["staged_grid"][0]["supplier"] == s["supplier_name"]


def test_setup_went_to_pending_then_approved(run):
    assert run["setup"]["setup_before_approve"]["isApprove"] in (False, 0, "False")
    assert run["setup"]["setup"]["isApprove"] in (True, 1, "True")
    codes = [r["code"] for r in run["setup"]["approval_queue"]]
    assert run["setup"]["code"] in codes, "code was not in the approval queue: %s" % codes


# ---- exe scan validation ------------------------------------------

def _by_expectation(run, expected):
    return [o for o in run["scan"]["outcomes"] if o["expected"] == expected]


def test_in_scope_items_are_accepted(run):
    bad = [o for o in _by_expectation(run, "accept") if not o["accepted"]]
    assert not bad, "in-scope scans were refused: %s" % bad


def test_other_category_is_rejected(run):
    """Category validation - the pre-existing behaviour that must keep
    working."""
    probes = _by_expectation(run, "reject_category")
    if not probes:
        pytest.skip("scenario had no other-category probe for this supplier")
    bad = [o for o in probes if o["accepted"]]
    assert not bad, "other-category items were ACCEPTED: %s" % bad


def test_other_supplier_same_category_is_rejected(run):
    """The enhancement itself. Spec: supplier must match (or be All) or
    the POS must not add the item and must show 'Not an Audit Item'.

    Observed 2026-09-15 on IAU-260915014: other suppliers' items in the
    scoped category were accepted with no popup. If this fails, that is
    the bug reproducing on fresh data - not a test problem."""
    probes = _by_expectation(run, "reject_supplier")
    assert probes, "scenario picked a category with only one supplier - cannot test"
    accepted = [o for o in probes if o["accepted"]]
    assert not accepted, (
        "supplier scoping NOT enforced at scan: other suppliers' items were "
        "accepted with popup=%s -> %s"
        % ([o["popup"] for o in accepted], [o["barcode"] for o in accepted])
    )
    missing_popup = [o for o in probes if not aa.popup_says({"text": o["popup"] or ""},
                                                            aa.POPUP_NOT_AUDIT_ITEM)]
    assert not missing_popup, "rejected but without the 'Not an Audit Item' popup: %s" % missing_popup


def test_sync_confirmed(run):
    assert run["scan"]["sync_popup"], "no popup after Fn+F1"
    assert aa.POPUP_SAVED in run["scan"]["sync_popup"].lower(), run["scan"]["sync_popup"]


# ---- database ------------------------------------------------------

def test_db_rows_match_accepted_scans(run):
    accepted = [o["barcode"] for o in run["scan"]["outcomes"] if o["accepted"]]
    synced = [r["ItemBarCode"] for r in run["db_rows"]]
    assert sorted(synced) == sorted(accepted), (synced, accepted)


def test_repeat_scans_are_summed(run):
    counted = {}
    for r in run["db_rows"]:
        counted[r["ItemBarCode"]] = counted.get(r["ItemBarCode"], 0) + float(r["NumPhysicalStock"])
    for bc in run["scenario"]["repeat_barcodes"]:
        assert counted.get(bc, 0) >= 2, "repeat of %s did not add up: %s" % (bc, counted)


# ---- report --------------------------------------------------------

def _rows_by_barcode(report):
    return {r["barcode"]: r for r in report["rows"]}


def test_report_by_supplier_shows_only_that_supplier(run):
    rep = run["reports"]["by_supplier"]
    assert not rep["no_data"], "report said No Data Found"
    names = {r["supplier"] for r in rep["rows"]}
    assert names == {run["scenario"]["supplier_name"]}, names


def test_report_by_supplier_rows_match_expected(run):
    rep = _rows_by_barcode(run["reports"]["by_supplier"])
    exp = {r["Barcode"]: r for r in run["expected_supplier"]["rows"]}
    assert set(rep) == set(exp), (sorted(rep), sorted(exp))
    for bc, e in exp.items():
        r = rep[bc]
        assert abs(r["audit_qty"] - e["counted"]) < TOL, (bc, r["audit_qty"], e["counted"])
        assert abs(r["system_qty"] - e["systemStock"]) < TOL, (bc, r["system_qty"], e["systemStock"])
        assert abs(r["diff_qty"] - e["variance"]) < TOL, (bc, r["diff_qty"], e["variance"])
        assert abs(r["diff_cost"] - e["costVariance"]) < TOL, (bc, r["diff_cost"], e["costVariance"])
        assert abs(r["diff_sale"] - e["salesVariance"]) < TOL, (bc, r["diff_sale"], e["salesVariance"])
        # the report's own arithmetic
        assert abs(r["system_cost"] - r["system_qty"] * r["avg_cost"]) < 0.05, bc
        assert abs(r["audit_sale"] - r["audit_qty"] * r["sale_price"]) < 0.05, bc
        assert abs(r["diff_qty"] - (r["short_qty"] + r["excess_qty"])) < TOL, bc


def test_report_by_supplier_totals(run):
    rep = run["reports"]["by_supplier"]
    exp = run["expected_supplier"]
    t = rep["total"]
    assert t, "no Total row"
    assert abs(t["audit_qty"] - exp["countedQuantity"]) < TOL
    assert abs(t["system_qty"] - exp["systemQuantity"]) < TOL
    assert abs(t["diff_qty"] - exp["varianceQuantity"]) < TOL
    assert abs(t["diff_cost"] - exp["costVariance"]) < TOL
    assert abs(t["diff_sale"] - exp["salesVariance"]) < TOL
    # total row == sum of rows shown
    for k in ("system_qty", "audit_qty", "diff_qty", "diff_cost", "diff_sale"):
        assert abs(t[k] - sum(r[k] for r in rep["rows"])) < 0.05, k


def test_report_all_suppliers_totals(run):
    rep = run["reports"]["all_suppliers"]
    exp = run["expected_all"]
    assert not rep["no_data"]
    assert len(rep["rows"]) == exp["itemCount"], (len(rep["rows"]), exp["itemCount"])
    t = rep["total"]
    assert abs(t["audit_qty"] - exp["countedQuantity"]) < TOL
    assert abs(t["diff_cost"] - exp["costVariance"]) < TOL
