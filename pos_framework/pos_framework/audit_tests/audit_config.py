# ============================================================
# AUDIT CONFIG - audit-only data/settings. Deliberately separate
# from the parent config.py so the existing suites are untouched.
#
# Everything below was read live out of the DemoStore database
# on 2026-09-15, not copied from a spec. Re-run
# audit_db.print_candidates() if a run starts failing for data
# reasons - these ids and barcodes are real rows and can change.
# ============================================================

# ---- where the audit runs -------------------------------------------
# The till is bound to a warehouse, and an item is only auditable if it
# has stock IN THAT WAREHOUSE. dbo.User 312 -> dbo.Employee 413 defaults
# to warehouse 16 ("DISPLAY", OfficeId 9 "Dhanmondi Outlet"), and every
# recent audit header carries exactly that pair - so these are the values
# a scan will actually be judged against.
AUDIT_WAREHOUSE_ID = 16
AUDIT_OFFICE_ID = 9
AUDIT_BRANCH_ID = 1
AUDIT_BRANCH_NAME = "Demo Super Shop"

# ---- web routes ------------------------------------------------------
# Relative to config.WEB_BASE_URL. The sidebar is a collapsed-by-default
# dropdown tree whose sibling <ul> intercepts clicks (see web_helpers'
# note), so the audit flow navigates by route too rather than by menu.
ROUTE_AUDIT_SETUP = "/inventory/audit-setup"
ROUTE_AUDIT_APPROVAL = "/approval/inventory/audit-config-approval"
ROUTE_POS_REPORTS = "/pos/reports"
AUDIT_ANALYSIS_REPORT_NAME = "Audit Analysis Report"

# ---- exe sync behaviour ---------------------------------------------
# The exe auto-syncs scanned rows to the server every 50 rows; below that
# the operator forces it with Fn+F1. Tests that scan fewer than 50 rows
# MUST force the sync or the report will legitimately show nothing.
AUTO_SYNC_ROW_THRESHOLD = 50
FORCE_SYNC_KEYS = "{F1}"          # Fn+F1 on this keyboard reaches F1

# ---- the "Stock Audit" adjustment type ------------------------------
# dbo.StockAdjustmentHeader.AdjustmentTypeId. 27 = Stock Audit,
# 28 = Stock Adjustment, 29 = Dispose. Filtering on this is what
# separates audit documents from ordinary adjustments.
ADJUSTMENT_TYPE_ID_STOCK_AUDIT = 27

# ---- verified test-data combos --------------------------------------
# Each entry is a (supplier, category, sub category) that genuinely has
# items in stock in warehouse 16 right now.

# The discriminating combo. Category 21863 "Kids Toys" / sub 11808 holds
# items from THREE different suppliers, so a supplier-scoped audit over
# this category must accept one supplier's items and reject the others.
# This is the single most valuable case for the new enhancement: a
# category-only audit would accept all eight items, so if the rejects
# below are accepted, supplier scoping is not being applied at all.
SHARED_CATEGORY = {
    "category_id": 21863,
    "category_name": "Kids Toys",
    "sub_category_id": 11808,
    "sub_category_name": "Plush & Soft Toys",
    "suppliers": {
        74450: {
            "name": "Audit Supplier",
            "barcodes": ["FG-01044", "FG-01045", "FG-01046"],
        },
        1: {
            "name": "313 Naogaon Distribution",
            "barcodes": ["FG-01040", "FG-01042", "KT000008"],
        },
        4: {
            "name": "A Fashionable Collection",
            "barcodes": ["KT000005", "KT000006"],
        },
    },
}

# A clean single-supplier combo for verifying report arithmetic: eight
# items, every one with a DISTINCT AvgRate (50..110) and selling price
# (100..150), so a wrong column or a swapped cost/sales figure in the
# report cannot coincidentally still add up.
CLEAN_SUPPLIER_COMBO = {
    "supplier_id": 107,
    "supplier_name": "American Suplier Ajmol",
    "category_id": 21885,
    "category_name": "Orange-1",
    "sub_category_id": 11830,
    "sub_category_name": "orange-2",
    "barcodes": [
        "565000001", "565000002", "565000003", "565000004",
        "565000005", "565000006", "565000007", "565000008",
    ],
}

# A larger single-supplier combo (32 items in one category) for the
# 50-row auto-sync path. Supplier 74450 has 36 items in stock overall:
# 32 in "Audit", 3 in "Kids Toys", 1 in "Fatcat".
BULK_SUPPLIER_COMBO = {
    "supplier_id": 74450,
    "supplier_name": "Audit Supplier",
    "category_id": 21848,
    "category_name": "Audit",
    "sub_category_id": 11794,
    "sub_category_name": "Audit",
}

# ---- scope-row shorthand --------------------------------------------
# 0 means "All" in tblAuditSetupRow for every one of the three scope
# columns. Legacy rows predating the enhancement have intSupplierId NULL,
# which the spec says must behave as All - worth asserting separately,
# since NULL and 0 are not the same thing in SQL and a naive
# `intSupplierId = 0` check would silently exclude all 105 legacy rows.
ALL = 0
