# ============================================================
# AUDIT DB - read-only audit lookups. Reuses db_helpers for the
# connection and its SELECT-only guard, so the safety story is
# unchanged: nothing here can write to the live POS database.
#
# WHY THIS EXISTS
# ---------------
# The audit flow spans two screens and three tables, and the two
# halves are joined only by a string code. Verifying it from the
# UI alone means trusting the same screen that produced the data.
# These lookups let a test state what the report SHOULD say,
# independently, before it ever looks at the report.
#
# TWO FACTS THAT SHAPE EVERYTHING BELOW (verified 2026-09-15 over
# all 10,970 audit scan rows in the database)
# ------------------------------------------------------------
# 1. An audit scan row stores ONLY the counted quantity. Every
#    variance column is left at zero: NumSystemStock = 0,
#    NumQuantity = 0, NumValue = 0, NumUpDownCostAmount = 0,
#    NumUpDownSalesAmount = 0 - on all 10,970 rows, with
#    NumPhysicalStock populated on 10,968 of them. Ordinary stock
#    adjustments (AdjustmentTypeId <> 27) DO populate those same
#    columns (2,960-3,013 of 3,015 rows), so this is specific to
#    the audit path, not a broken column.
#    => Any expected variance must be computed from live stock
#       (expected_variance_rows below), never read off the row.
# 2. An audit scan row's SupplierId is ALWAYS 0 and SupplierName
#    always blank, even when the audit scope named a supplier
#    (e.g. IAU-260915012 was scoped to supplier 107 and both its
#    rows carry SupplierId 0). Non-audit adjustment rows carry a
#    real supplier on 3,013 of 3,015 rows.
#    => Supplier-wise report filtering CANNOT come from the scan
#       row; it has to join dbo.Item.SupplierId. A report that
#       filters on StockAdjustmentRow.SupplierId will always come
#       back empty for a named supplier.
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_helpers as db

from audit_tests import audit_config as acfg


# ---- audit setup (the scope) ---------------------------------------

def get_audit_setup(code):
    """One audit setup header by its code (e.g. 'IAU-260915012'), or
    None. isApprove is the gate the exe checks: an unapproved audit
    never appears in the app's audit-code list, so a test that scans
    before approving fails for a setup reason, not a bug."""
    rows = db.query(
        "SELECT AuditSetupId, strAuditSetupCode, intAccountId, intBranchId, intOfficeId, "
        "intWarehouseId, CAST(dteStartDate AS date) AS StartDate, "
        "CAST(dteEndDate AS date) AS EndDate, isComplete, isApprove, isActive, isReject, "
        "intActionBy, intApproveBy, strRemarks, dteServerDateTime "
        "FROM pos.tblAuditSetupHead WHERE strAuditSetupCode = ?",
        [code]
    )
    return rows[0] if rows else None


def get_latest_audit_setup():
    """Newest audit setup regardless of state - used right after the web
    UI saves one, to pick up the code the server generated."""
    rows = db.query(
        "SELECT TOP 1 AuditSetupId, strAuditSetupCode, isApprove, isComplete, isReject, "
        "intWarehouseId, intOfficeId, dteServerDateTime "
        "FROM pos.tblAuditSetupHead ORDER BY AuditSetupId DESC"
    )
    return rows[0] if rows else None


def get_pending_audit_setups():
    """Audit setups saved but not yet approved - what the Audit Config
    Approval screen should be listing.

    Note the live data: all 84 existing setups have isApprove = 1 and
    intApproveBy = 0. So approval sets isApprove without recording who
    approved it, and an empty result here means "nothing pending", not
    "approval is broken"."""
    return db.query(
        "SELECT AuditSetupId, strAuditSetupCode, intOfficeId, intWarehouseId, "
        "CAST(dteStartDate AS date) AS StartDate, CAST(dteEndDate AS date) AS EndDate, "
        "intActionBy FROM pos.tblAuditSetupHead "
        "WHERE isApprove = 0 AND isActive = 1 AND isReject = 0 "
        "ORDER BY AuditSetupId DESC"
    )


def get_audit_scope(audit_setup_id):
    """The scope rows for one audit - the (supplier, category, sub
    category) triples that decide which items may be scanned.

    intSupplierId is the enhancement's new column and is NULLABLE: 105
    of the 119 existing rows predate it and are NULL. The spec says
    legacy rows must behave as All Supplier, so NULL is normalised to
    audit_config.ALL (0) here rather than left to trip up callers - a
    plain "intSupplierId = 0" comparison would silently exclude every
    legacy row."""
    rows = db.query(
        "SELECT RowId, AuditSetupId, intSupplierId, intCategoryId, strCategoryCode, "
        "strCategoryName, intSubCategoryId, strSubCategoryName, isActive "
        "FROM pos.tblAuditSetupRow WHERE AuditSetupId = ? AND isActive = 1 "
        "ORDER BY RowId",
        [audit_setup_id]
    )
    for r in rows:
        r["_supplier_was_null"] = r["intSupplierId"] is None
        if r["intSupplierId"] is None:
            r["intSupplierId"] = acfg.ALL
    return rows


def scope_rows_raw(audit_setup_id):
    """Same rows WITHOUT the NULL normalisation, for the one test that
    needs to tell a legacy NULL apart from an explicit 0."""
    return db.query(
        "SELECT RowId, intSupplierId, intCategoryId, intSubCategoryId, isActive "
        "FROM pos.tblAuditSetupRow WHERE AuditSetupId = ? ORDER BY RowId",
        [audit_setup_id]
    )


# ---- the matching rule ---------------------------------------------

def item_matches_scope_row(item, scope_row):
    """The spec's matching rule for ONE scope row:

        (supplier = item supplier OR supplier is All)
        AND (category = item category OR category is All)
        AND (sub category = item sub category OR sub category is All)

    item needs SupplierId / ItemCategoryId / ItemSubCategoryId."""
    sup = scope_row["intSupplierId"]
    cat = scope_row["intCategoryId"]
    sub = scope_row["intSubCategoryId"]
    if sup is None:
        sup = acfg.ALL
    return (
        (int(sup) == acfg.ALL or int(sup) == int(item["SupplierId"]))
        and (int(cat) == acfg.ALL or int(cat) == int(item["ItemCategoryId"]))
        and (int(sub) == acfg.ALL or int(sub) == int(item["ItemSubCategoryId"]))
    )


def item_in_scope(item, scope_rows):
    """True if ANY scope row matches - the spec is explicit that one
    matching row is enough ("If any existing Audit Setup Row matches,
    the item will be allowed for audit")."""
    return any(item_matches_scope_row(item, r) for r in scope_rows)


# ---- items, in and out of scope ------------------------------------

_ITEM_COLS = """
    i.ItemId, i.ItemName, i.ItemCode, i.Barcode, i.SupplierId,
    i.ItemCategoryId, i.ItemCategoryName, i.ItemSubCategoryId, i.ItemSubCategoryName,
    i.IsActive, i.CurrentSellingPrice, i.AvgRate, i.UomName, i.BranchName
"""


def find_items(supplier_id=None, category_id=None, sub_category_id=None,
               in_stock_only=True, active_only=True):
    """Items matching one (supplier, category, sub category) triple, in
    the audit warehouse.

    in_stock_only defaults True because the till only offers items that
    have stock in ITS warehouse - an item with stock in another
    warehouse is silently unavailable (the same warehouse rule that
    makes barcode 2869 unsellable at this till)."""
    sql = "SELECT " + _ITEM_COLS
    if in_stock_only:
        sql += ", b.CurrentStock FROM dbo.Item i "
        sql += ("JOIN dbo.ItemWarehouseBalance b ON b.ItemId = i.ItemId "
                "AND b.WarehouseId = ? AND b.CurrentStock > 0 ")
    else:
        sql += ", ISNULL(b.CurrentStock, 0) AS CurrentStock FROM dbo.Item i "
        sql += ("LEFT JOIN dbo.ItemWarehouseBalance b ON b.ItemId = i.ItemId "
                "AND b.WarehouseId = ? ")
    params = [acfg.AUDIT_WAREHOUSE_ID]

    sql += "WHERE i.BranchName = ? "
    params.append(acfg.AUDIT_BRANCH_NAME)
    if active_only:
        sql += "AND i.IsActive = 1 "
    if supplier_id is not None and supplier_id != acfg.ALL:
        sql += "AND i.SupplierId = ? "
        params.append(supplier_id)
    if category_id is not None and category_id != acfg.ALL:
        sql += "AND i.ItemCategoryId = ? "
        params.append(category_id)
    if sub_category_id is not None and sub_category_id != acfg.ALL:
        sql += "AND i.ItemSubCategoryId = ? "
        params.append(sub_category_id)
    sql += "ORDER BY i.ItemId"
    return db.query(sql, params)


def find_items_by_barcodes(barcodes):
    """Resolve a list of typed barcodes the way the POS does - Barcode OR
    ItemCode - and report stock in the audit warehouse. Preserves the
    caller's order so a scan sequence stays aligned with its
    expectations, and yields None for anything that resolves to nothing."""
    out = []
    for bc in barcodes:
        rows = db.query(
            "SELECT " + _ITEM_COLS + ", ISNULL(b.CurrentStock, 0) AS CurrentStock "
            "FROM dbo.Item i "
            "LEFT JOIN dbo.ItemWarehouseBalance b ON b.ItemId = i.ItemId "
            "  AND b.WarehouseId = ? "
            "WHERE (i.Barcode = ? OR i.ItemCode = ?) AND i.BranchName = ? "
            "ORDER BY CASE WHEN i.IsActive = 1 THEN 0 ELSE 1 END, i.ItemId",
            [acfg.AUDIT_WAREHOUSE_ID, bc, bc, acfg.AUDIT_BRANCH_NAME]
        )
        out.append(rows[0] if rows else None)
    return out


def split_by_scope(barcodes, scope_rows):
    """Given barcodes and a scope, return (in_scope, out_of_scope,
    unresolved) - exactly the three buckets a scan test needs: what
    should be accepted, what must raise "Not an Audit Item", and what
    never resolved to an item at all."""
    in_scope, out_of_scope, unresolved = [], [], []
    for bc, item in zip(barcodes, find_items_by_barcodes(barcodes)):
        if item is None:
            unresolved.append(bc)
        elif item_in_scope(item, scope_rows):
            in_scope.append(item)
        else:
            out_of_scope.append(item)
    return in_scope, out_of_scope, unresolved


# ---- the scan (what the exe sent) ----------------------------------

def get_audit_document(code):
    """The StockAdjustmentHeader the exe writes for an audit code.

    The audit setup and this document share the code but live in
    different tables, and AdjustmentTypeId = 27 ('Stock Audit') is what
    separates an audit from an ordinary adjustment or a dispose."""
    rows = db.query(
        "SELECT StockAdjustmentId, StockAdjustmentCode, AccountId, BranchId, OfficeId, "
        "WarehouseId, AdjustmentDate, AdjustmentTypeId, AdjustmentTypeName, "
        "TotalQuantity, TotalValue, ActionById, ActionByName, IsApprove, "
        "ApproveById, ApproveByName, IsActive, isFinished, DteServerDateTime "
        "FROM dbo.StockAdjustmentHeader "
        "WHERE StockAdjustmentCode = ? AND AdjustmentTypeId = ?",
        [code, acfg.ADJUSTMENT_TYPE_ID_STOCK_AUDIT]
    )
    return rows[0] if rows else None


def get_scan_rows(code):
    """Every row the exe synced for one audit code, with the item's real
    supplier/category joined back in.

    SupplierId/SupplierName on the scan row itself are always 0/blank
    (see module header), so itemSupplierId below - taken from dbo.Item -
    is the only usable supplier for this row."""
    return db.query(
        "SELECT r.RowId, r.SerialNo, r.ItemId, r.ItemName, r.ItemBarCode, "
        "r.SupplierId AS rowSupplierId, r.SupplierName AS rowSupplierName, "
        "r.NumCostPrice, r.NumSalesPrice, r.CurrentStock, r.NumSystemStock, "
        "r.NumPhysicalStock, r.NumQuantity, r.NumValue, "
        "r.NumUpDownCostAmount, r.NumUpDownSalesAmount, "
        "r.WarehouseId, r.CounterId, r.ActionDatetime, "
        "i.SupplierId AS itemSupplierId, i.ItemCategoryId AS itemCategoryId, "
        "i.ItemSubCategoryId AS itemSubCategoryId, i.IsActive AS itemIsActive, "
        "i.AvgRate, i.CurrentSellingPrice "
        "FROM dbo.StockAdjustmentRow r "
        "JOIN dbo.StockAdjustmentHeader h ON h.StockAdjustmentId = r.StockAdjustmentId "
        "LEFT JOIN dbo.Item i ON i.ItemId = r.ItemId "
        "WHERE h.StockAdjustmentCode = ? AND h.AdjustmentTypeId = ? "
        "ORDER BY r.SerialNo, r.RowId",
        [code, acfg.ADJUSTMENT_TYPE_ID_STOCK_AUDIT]
    )


def scanned_quantity_by_item(code):
    """{ItemId: total counted quantity} for one audit.

    Summed, not per row: the spec allows the same item to be scanned
    repeatedly, and each scan is its own row with its own SerialNo. A
    test that scans one item three times must compare against the sum,
    and the report is expected to aggregate the same way."""
    out = {}
    for r in get_scan_rows(code):
        qty = float(r["NumPhysicalStock"] or 0)
        out[r["ItemId"]] = out.get(r["ItemId"], 0.0) + qty
    return out


# ---- what the report SHOULD say ------------------------------------

def expected_variance_rows(code):
    """Per item: counted quantity vs the stock the system currently
    believes, and the resulting value variance - computed here because
    the scan rows carry zeros for all of it (see module header).

        variance       = counted - system stock
        cost variance  = variance * AvgRate
        sales variance = variance * CurrentSellingPrice

    IMPORTANT, and a limitation to state rather than hide: system stock
    is read LIVE from ItemWarehouseBalance at call time, not as of the
    scan. If anything sells between the scan and this call, the variance
    moves. For a controlled test run that is fine; for interpreting an
    old audit it is not."""
    counted = scanned_quantity_by_item(code)
    if not counted:
        return []

    ids = list(counted.keys())
    placeholders = ",".join("?" for _ in ids)
    stock = {
        r["ItemId"]: float(r["CurrentStock"])
        for r in db.query(
            "SELECT b.ItemId, ISNULL(SUM(b.CurrentStock), 0) AS CurrentStock "
            "FROM dbo.ItemWarehouseBalance b "
            "WHERE b.WarehouseId = ? AND b.ItemId IN (" + placeholders + ") "
            "GROUP BY b.ItemId",
            [acfg.AUDIT_WAREHOUSE_ID] + ids
        )
    }
    meta = {
        r["ItemId"]: r
        for r in db.query(
            "SELECT ItemId, ItemName, Barcode, SupplierId, ItemCategoryId, "
            "ItemSubCategoryId, AvgRate, CurrentSellingPrice, IsActive "
            "FROM dbo.Item WHERE ItemId IN (" + placeholders + ")", ids
        )
    }

    out = []
    for item_id, qty in counted.items():
        m = meta.get(item_id, {})
        system = stock.get(item_id, 0.0)
        variance = qty - system
        avg = float(m.get("AvgRate") or 0)
        sell = float(m.get("CurrentSellingPrice") or 0)
        out.append({
            "ItemId": item_id,
            "ItemName": m.get("ItemName"),
            "Barcode": m.get("Barcode"),
            "SupplierId": m.get("SupplierId"),
            "ItemCategoryId": m.get("ItemCategoryId"),
            "ItemSubCategoryId": m.get("ItemSubCategoryId"),
            "itemIsActive": m.get("IsActive"),
            "counted": qty,
            "systemStock": system,
            "variance": variance,
            "costVariance": round(variance * avg, 2),
            "salesVariance": round(variance * sell, 2),
            "avgRate": avg,
            "sellingPrice": sell,
        })
    return sorted(out, key=lambda r: r["ItemId"])


def expected_report_totals(code, supplier_id=None, category_id=None):
    """Totals a filtered Audit Analysis Report should add up to.

    supplier_id/category_id narrow the expectation the same way the
    report's own filters are supposed to - this is what makes "with
    supplier X selected, only X's rows show" an assertion instead of an
    eyeball check."""
    rows = expected_variance_rows(code)
    if supplier_id is not None and supplier_id != acfg.ALL:
        rows = [r for r in rows if int(r["SupplierId"] or 0) == int(supplier_id)]
    if category_id is not None and category_id != acfg.ALL:
        rows = [r for r in rows if int(r["ItemCategoryId"] or 0) == int(category_id)]
    return {
        "itemCount": len(rows),
        "countedQuantity": round(sum(r["counted"] for r in rows), 2),
        "systemQuantity": round(sum(r["systemStock"] for r in rows), 2),
        "varianceQuantity": round(sum(r["variance"] for r in rows), 2),
        "costVariance": round(sum(r["costVariance"] for r in rows), 2),
        "salesVariance": round(sum(r["salesVariance"] for r in rows), 2),
        "rows": rows,
    }


# ---- dynamic scenario selection ------------------------------------
# Every run picks its own supplier / category / items from what is in
# stock RIGHT NOW, so the suite never depends on a hardcoded combo that
# can quietly go stale, and no two runs audit the same thing. The only
# fixed inputs are the shape of the scenario (how many items, how many
# repeats) - the data is always live.

import random as _random


def _rng(seed=None):
    """Seeded when the caller wants a reproducible re-run of a failure,
    unseeded (fresh data every time) otherwise. The seed used is printed
    by the test so a failing run can always be replayed."""
    return _random.Random(seed)


def scope_candidates(min_items=2, min_stock=1, active_only=True):
    """Every (supplier, category, sub category) combo that has at least
    `min_items` distinct items with stock in the audit warehouse.

    Excludes items with a '99' barcode prefix (weighing-scale codes are
    parsed as itemcode+weight and would scan as a different item) and
    barcodes that collide with another item's Barcode/ItemCode (the till
    resolves both, so the wrong row could land in the audit)."""
    return db.query(
        "SELECT i.SupplierId, p.PartnerName AS SupplierName, "
        "       i.ItemCategoryId, i.ItemCategoryName, "
        "       i.ItemSubCategoryId, i.ItemSubCategoryName, "
        "       COUNT(*) AS items, SUM(b.CurrentStock) AS stock "
        "FROM dbo.Item i "
        "JOIN dbo.ItemWarehouseBalance b ON b.ItemId = i.ItemId "
        "  AND b.WarehouseId = ? AND b.CurrentStock >= ? "
        "JOIN dbo.Partner p ON p.PartnerId = i.SupplierId AND p.PartnerTypeId = 2 "
        "WHERE i.BranchName = ? AND i.SupplierId > 0 "
        "  AND i.Barcode IS NOT NULL AND LEN(i.Barcode) > 0 "
        "  AND i.Barcode NOT LIKE '99%' "
        + ("  AND i.IsActive = 1 " if active_only else "") +
        "  AND NOT EXISTS (SELECT 1 FROM dbo.Item o WHERE o.ItemCode = i.Barcode AND o.ItemId <> i.ItemId) "
        "  AND NOT EXISTS (SELECT 1 FROM dbo.Item o WHERE o.Barcode  = i.Barcode AND o.ItemId <> i.ItemId) "
        "GROUP BY i.SupplierId, p.PartnerName, i.ItemCategoryId, i.ItemCategoryName, "
        "         i.ItemSubCategoryId, i.ItemSubCategoryName "
        "HAVING COUNT(*) >= ? "
        "ORDER BY i.SupplierId, i.ItemCategoryId",
        [acfg.AUDIT_WAREHOUSE_ID, min_stock, acfg.AUDIT_BRANCH_NAME, min_items]
    )


def shared_category_candidates(min_items_per_supplier=1, min_suppliers=2):
    """Categories whose in-stock items come from at least `min_suppliers`
    different suppliers - the only kind of category that can prove
    supplier scoping is enforced, because a supplier-scoped audit over
    it must accept one supplier's items and reject the others'."""
    rows = scope_candidates(min_items=min_items_per_supplier)
    by_cat = {}
    for r in rows:
        key = (r["ItemCategoryId"], r["ItemSubCategoryId"])
        by_cat.setdefault(key, []).append(r)
    out = []
    for key, sups in by_cat.items():
        if len({s["SupplierId"] for s in sups}) >= min_suppliers:
            out.append({
                "category_id": key[0],
                "category_name": sups[0]["ItemCategoryName"],
                "sub_category_id": key[1],
                "sub_category_name": sups[0]["ItemSubCategoryName"],
                "suppliers": sups,
            })
    return out


def pick_supplier_scope_scenario(seed=None, in_scope_items=3, repeats=1,
                                 max_price=None):
    """Build one supplier-wise scenario from live data:

      scope     one supplier + one category (+ sub category)
      accept    N distinct in-scope barcodes, some scanned more than once
      reject    same category, OTHER suppliers   (supplier check)
      reject    same supplier, OTHER category    (category check)

    Picks randomly among the categories that have >= 2 suppliers, then
    randomly among that category's suppliers. Returns a dict the test
    drives straight from; `seed` reproduces a previous pick."""
    rng = _rng(seed)
    cats = shared_category_candidates()
    if not cats:
        raise AssertionError("no category with items from >= 2 suppliers in stock "
                             "at warehouse %s" % acfg.AUDIT_WAREHOUSE_ID)
    cat = rng.choice(cats)
    chosen = rng.choice(cat["suppliers"])
    others = [s for s in cat["suppliers"] if s["SupplierId"] != chosen["SupplierId"]]

    in_items = find_items(chosen["SupplierId"], cat["category_id"], cat["sub_category_id"])
    if max_price is not None:
        in_items = [i for i in in_items if float(i["CurrentSellingPrice"]) <= max_price] or in_items
    rng.shuffle(in_items)
    accept = in_items[:in_scope_items]
    # repeat scans of random in-scope items (the spec allows repeats)
    repeat_bcs = [rng.choice(accept)["Barcode"] for _ in range(repeats)] if accept else []

    reject_supplier = []
    for o in others:
        rows = find_items(o["SupplierId"], cat["category_id"], cat["sub_category_id"])
        if rows:
            reject_supplier.append(rng.choice(rows))

    other_cats = [c for c in scope_candidates(min_items=1)
                  if c["SupplierId"] == chosen["SupplierId"]
                  and c["ItemCategoryId"] != cat["category_id"]]
    reject_category = []
    if other_cats:
        oc = rng.choice(other_cats)
        rows = find_items(chosen["SupplierId"], oc["ItemCategoryId"], oc["ItemSubCategoryId"])
        if rows:
            reject_category.append(rng.choice(rows))

    tag = "%s-%04d" % (time.strftime("%y%m%d%H%M%S"), rng.randint(0, 9999))
    return {
        "seed": seed,
        "tag": tag,
        "description": "AUTO %s | %s | %s" % (tag, chosen["SupplierName"], cat["category_name"]),
        "supplier_id": chosen["SupplierId"],
        "supplier_name": chosen["SupplierName"],
        "category_id": cat["category_id"],
        "category_name": cat["category_name"],
        "sub_category_id": cat["sub_category_id"],
        "sub_category_name": cat["sub_category_name"],
        "accept": accept,
        "repeat_barcodes": repeat_bcs,
        "reject_other_supplier": reject_supplier,
        "reject_other_category": reject_category,
        "all_suppliers_in_category": [
            {"id": s["SupplierId"], "name": s["SupplierName"], "items": s["items"]}
            for s in cat["suppliers"]
        ],
    }


def scan_plan(scenario, seed=None):
    """The barcode sequence to type, shuffled so the order differs per
    run, with the expected outcome for each: ('accept' | 'reject_supplier'
    | 'reject_category')."""
    rng = _rng(seed)
    plan = [(i["Barcode"], "accept") for i in scenario["accept"]]
    plan += [(b, "accept") for b in scenario["repeat_barcodes"]]
    plan += [(i["Barcode"], "reject_supplier") for i in scenario["reject_other_supplier"]]
    plan += [(i["Barcode"], "reject_category") for i in scenario["reject_other_category"]]
    rng.shuffle(plan)
    return plan


import time  # noqa: E402  (used by pick_supplier_scope_scenario's tag)


# ---- diagnostics ---------------------------------------------------

def print_candidates(min_items=2, limit=15):
    """(supplier, category, sub category) combos that genuinely have
    stock in the audit warehouse right now. Run this when the combos
    hardcoded in audit_config go stale."""
    rows = db.query(
        "SELECT TOP (?) i.SupplierId, p.PartnerName AS supplier, i.ItemCategoryId, "
        "i.ItemCategoryName, i.ItemSubCategoryId, i.ItemSubCategoryName, "
        "COUNT(*) AS items, SUM(b.CurrentStock) AS stock "
        "FROM dbo.Item i "
        "JOIN dbo.ItemWarehouseBalance b ON b.ItemId = i.ItemId "
        "  AND b.WarehouseId = ? AND b.CurrentStock > 0 "
        "LEFT JOIN dbo.Partner p ON p.PartnerId = i.SupplierId "
        "WHERE i.IsActive = 1 AND i.BranchName = ? AND i.SupplierId > 0 "
        "GROUP BY i.SupplierId, p.PartnerName, i.ItemCategoryId, i.ItemCategoryName, "
        "         i.ItemSubCategoryId, i.ItemSubCategoryName "
        "HAVING COUNT(*) >= ? ORDER BY COUNT(*) DESC",
        [limit, acfg.AUDIT_WAREHOUSE_ID, acfg.AUDIT_BRANCH_NAME, min_items]
    )
    for r in rows:
        print("supplier %-7s %-26s cat %-6s %-22s sub %-6s %-22s %3d items"
              % (r["SupplierId"], str(r["supplier"])[:26], r["ItemCategoryId"],
                 str(r["ItemCategoryName"])[:22], r["ItemSubCategoryId"],
                 str(r["ItemSubCategoryName"])[:22], r["items"]))
    return rows


def scenario_from_env(env, seed=None, in_scope_items=3, repeats=1):
    """Same shape as pick_supplier_scope_scenario(), but built from an
    environment audit_env.build_environment() just created - so the
    audit only ever touches suppliers/items/stock this run made."""
    rng = _rng(seed)
    items = env["items"]
    cat_ids = sorted({(i["ItemCategoryId"], i["ItemSubCategoryId"]) for i in items})
    cat_id, sub_id = rng.choice(cat_ids)
    sup = rng.choice(env["suppliers"])
    sup_id, sup_name = sup["PartnerId"], sup["PartnerName"]

    def of(supplier_id, category_id=None, not_category=None):
        out = []
        for i in items:
            if int(i["SupplierId"]) != int(supplier_id):
                continue
            if category_id is not None and int(i["ItemCategoryId"]) != int(category_id):
                continue
            if not_category is not None and int(i["ItemCategoryId"]) == int(not_category):
                continue
            out.append(i)
        return out

    mine = of(sup_id, cat_id)
    rng.shuffle(mine)
    accept = mine[:in_scope_items]
    repeat_bcs = [rng.choice(accept)["Barcode"] for _ in range(repeats)] if accept else []
    reject_supplier = []
    for s in env["suppliers"]:
        if s["PartnerId"] == sup_id:
            continue
        rows = of(s["PartnerId"], cat_id)
        if rows:
            reject_supplier.append(rng.choice(rows))
    others = of(sup_id, not_category=cat_id)
    reject_category = [rng.choice(others)] if others else []
    sample = accept[0] if accept else items[0]
    tag = "%s-%04d" % (env["tag"], rng.randint(0, 9999))
    return {
        "seed": seed, "tag": tag,
        "description": "AUTO %s | %s | %s" % (tag, sup_name, sample["ItemCategoryName"]),
        "supplier_id": sup_id, "supplier_name": sup_name,
        "category_id": cat_id, "category_name": sample["ItemCategoryName"],
        "sub_category_id": sub_id, "sub_category_name": sample["ItemSubCategoryName"],
        "accept": accept, "repeat_barcodes": repeat_bcs,
        "reject_other_supplier": reject_supplier, "reject_other_category": reject_category,
        "all_suppliers_in_category": [
            {"id": s["PartnerId"], "name": s["PartnerName"], "items": len(of(s["PartnerId"], cat_id))}
            for s in env["suppliers"]],
    }


def multi_scope_scenario(env, seed=None):
    """One audit with several scope rows - each supplier paired with one
    category (supplier i -> category i mod n), the way the operator
    audits several suppliers in one go. Returns the rows to set up, every
    in-scope item (all must be scanned), and out-of-scope probes: for each
    supplier an item of theirs in a category NOT scoped for them."""
    rng = _rng(seed)
    items = env["items"]
    cats = sorted({(i["ItemCategoryId"], i["ItemCategoryName"], i["ItemSubCategoryId"], i["ItemSubCategoryName"]) for i in items})
    sups = sorted(env["suppliers"], key=lambda s: s["PartnerId"])
    rng.shuffle(cats)
    rows, accept, probes = [], [], []
    for n, s in enumerate(sups):
        cat = cats[n % len(cats)]
        rows.append({"supplier_id": s["PartnerId"], "supplier_name": s["PartnerName"],
                     "category_id": cat[0], "category_name": cat[1],
                     "sub_category_id": cat[2], "sub_category_name": cat[3]})
        mine = [i for i in items if int(i["SupplierId"]) == int(s["PartnerId"])]
        accept += [i for i in mine if int(i["ItemCategoryId"]) == int(cat[0])]
        out = [i for i in mine if int(i["ItemCategoryId"]) != int(cat[0])]
        if out:
            probes.append(rng.choice(out))
    tag = "%s-%04d" % (env["tag"], rng.randint(0, 9999))
    plan = [(i["Barcode"], "accept") for i in accept] + [(i["Barcode"], "reject_category") for i in probes]
    rng.shuffle(plan)
    return {"seed": seed, "tag": tag,
            "description": "AUTO multi-scope %s | %d suppliers" % (tag, len(rows)),
            "rows": rows, "accept": accept, "probes": probes, "plan": plan}
