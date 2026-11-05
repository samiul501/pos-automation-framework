# audit_tests

Self-contained automation for the POS **Stock Audit** flow, including the
new **supplier-wise scope** enhancement (spec: "Audit – Supplier Wise Scope
Enhancement").

## Isolation

Nothing in the existing suites changes. This package only ever *imports*
`config.py`, `db_helpers.py`, `pos_helpers.py` and `web_helpers.py` from the
parent package - it never edits them, and no file outside `audit_tests/` is
touched. Audit-specific settings live in `audit_config.py`, so `config.py`
stays as it is.

## The flow being automated

    1. web   devdemostore -> Inventory -> Audit Setup
             (Supplier + Category + Sub Category scope rows)  -> Save -> pending
    2. web   Approval -> Inventory -> Audit Config Approval   -> Approve
    3. exe   the approved audit code appears; scan items in scope
             (same item may be scanned repeatedly)
    4. sync  auto-syncs every 50 rows; below 50 use Fn+F1
    5. web   POS -> Report -> Audit Analysis Report -> verify the numbers

## Data model (verified live, 2026-09-15)

The scope and the scan live in two different places, joined by the audit code:

    pos.tblAuditSetupHead    strAuditSetupCode = 'IAU-260915012', isApprove
      +- pos.tblAuditSetupRow    intSupplierId / intCategoryId / intSubCategoryId
                                 <- THE SCOPE (intSupplierId is the new column)

    dbo.StockAdjustmentHeader   StockAdjustmentCode = the SAME code,
                                AdjustmentTypeId = 27 ('Stock Audit')
      +- dbo.StockAdjustmentRow    SupplierId, NumSystemStock, NumPhysicalStock,
                                   NumQuantity, NumUpDownCostAmount/SalesAmount
                                   <- THE SCAN, and what the report totals

`pos.sprAuditRowDataInsert` is the proc the exe calls; it inserts straight
into `dbo.StockAdjustmentRow`. Confirmed by reading its definition.

Tables that look relevant and are NOT: `dbo.tblItemForAudit` (stale 2023
DEMO_STORE snapshot), `pos.MonthlyPhysicalStockUpdate` (empty),
`dbo.PhysicalStock`/`PhysicalStockLine` (empty), `dbo.tblAuditLog` (generic
UI change log, nothing to do with stock audit).

## Files

| file | role |
|---|---|
| `audit_config.py` | audit-only settings (warehouse/office, routes, sync threshold) |
| `audit_db.py` | read-only DB lookups + **live random scenario picking** + expected report maths |
| `audit_web.py` | Playwright: create setup, approve, run/parse Audit Summary Report |
| `audit_actions.py` | exe: open Audit screen, pick code, scan, detect popups, Fn+F1 |
| `audit_flow.py` | runs the whole chain once and records evidence (`python -m audit_tests.audit_flow`) |
| `test_audit_supplier_scope.py` | pytest assertions over one recorded run |

## Every run uses different data

`audit_db.pick_supplier_scope_scenario()` chooses, from what is in stock in the
audit warehouse right now: a category that has items from >= 2 suppliers, one
of those suppliers as the scope, N in-scope items (some scanned twice), one
item from each OTHER supplier in that category (must be rejected - the
enhancement), and one item of the same supplier from ANOTHER category (must
be rejected - existing behaviour). The description carries a unique tag.

    pytest audit_tests/ -s -v                 # fresh random data
    AUDIT_SEED=4242 pytest audit_tests/ -s    # replay that exact pick
    AUDIT_HEADED=1  pytest audit_tests/ -s    # watch the browser

The seed is printed at the start and the full evidence is written to
`audit_tests/last_run_<seed>.json`.

## Findings so far (2026-09-15, IAU-260915014)

- Setup, pending -> approval queue -> approve, exe code list, Fn+F1 sync and the
  Audit Summary Report all work; report rows and totals matched the
  independent DB calculation to the paisa, repeats were summed, and the
  supplier filter showed only that supplier.
- **Bug:** the exe does not validate supplier at scan time. Items of OTHER
  suppliers in the scoped category were accepted with no popup; items of
  another category were correctly refused ("Barcode[...] Not Found"). Test
  `test_other_supplier_same_category_is_rejected` reproduces it on fresh data.
- Scan rows always carry `SupplierId = 0` and zero variance columns; the report
  derives both from `dbo.Item` / live stock, which is why it is still correct.

## Self-built environment + one-session flow (2026-09-16)

`audit_env.py` creates the audit's own data through the web UI, via the sidebar
(direct URLs lose the menu context and the supplier form then saves nothing):
3-5 suppliers (Office + Partner Name + Mobile + Address) -> 8-10 items each
(Ant form, ids `MGMForm_*`, random cost/price, some AutoBarCode, every supplier
gets items in every chosen category) -> one Direct Receive per supplier
(Office Dhanmondi, Warehouse DISPLAY, VAT 5%).

`audit_flow.run_single_session()` then does everything in ONE login: audit
setup with one scope row per supplier (Sup-i + Cat-i) -> approve -> exe scan of
every in-scope item plus one out-of-scope probe per supplier -> Fn+F1 -> DB ->
Audit Summary Report per supplier (audit id, supplier, Based On = All Items,
Is Details on). The browser stays open during the exe part.

    python -m audit_tests.audit_flow --headed                    # build + run
    python -m audit_tests.audit_flow --env-tag 260916164705      # reuse data
    AUDIT_ENV_TAG=260916164705 pytest audit_tests/test_audit_multi_scope.py -s -v --alluredir=allure-results-audit
    allure generate allure-results-audit -o allure-report-audit --clean

Lessons that each cost a run: react-select `has_text` is a substring match -
asking for sub-category "COSMETICS#" picked "COLOR COSMETICS#" and the whole
audit was scoped wrong (now exact-match); Add refuses a scope row without a
sub-category although the spec calls it optional; the report's audit dropdown
reloads after the office pick, so the audit is re-picked until its hidden
input is set.
