# ============================================================
# BRANCH SETTINGS - the per-branch switches the console can set.
#
# Today that is one switch: VAT-inclusive pricing. It decides
# whether a rate typed into Purchase Receive ALREADY contains VAT
# (so VAT is extracted out of it) or whether VAT is added on top.
# It changes what every screen shows and what gets stored, and it
# is set per branch, so a tester needs it per branch too.
#
# TWO COLUMNS, NOT ONE
# --------------------
# dbo.Branch carries both `IsVATInclusive` and `isInclusiveVAT`,
# and every branch has always had them equal. Which one the app
# reads is not documented anywhere, so both are written together:
# setting only the one you happen to name can leave the screen
# unchanged and look like the switch does nothing.
#
# WRITING
# -------
# db_helpers refuses anything but SELECT by design, so a write
# opens its own connection. Each write is one transaction that
# commits only if exactly one row moved - a WHERE that matched
# more branches than intended rolls back instead of quietly
# reconfiguring someone else's outlet.
# ============================================================

import os
import sys

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
POS_FRAMEWORK_DIR = os.path.join(os.path.dirname(DASHBOARD_DIR), "pos_framework")
if POS_FRAMEWORK_DIR not in sys.path:
    sys.path.insert(0, POS_FRAMEWORK_DIR)

# Kept together so a future switch is added in one place.
VAT_COLUMNS = ("IsVATInclusive", "isInclusiveVAT")


def _db():
    import db_helpers
    return db_helpers


def read():
    """Every branch and the state of its switches."""
    try:
        db = _db()
        if not db.is_available():
            return {"ok": False, "branches": [],
                    "message": (db.unavailable_reason() or "database not reachable")[:160]}
        rows = db._query("""
            SELECT BranchId, BranchName, AccountId, AccountName,
                   IsVATInclusive, isInclusiveVAT
            FROM dbo.Branch
            ORDER BY AccountId, BranchId
        """)
    except Exception as e:
        return {"ok": False, "branches": [], "message": str(e)[:160]}

    branches = []
    for r in rows:
        primary = bool(r["IsVATInclusive"])
        secondary = bool(r["isInclusiveVAT"])
        branches.append({
            "id": r["BranchId"],
            "name": r["BranchName"],
            "account_id": r["AccountId"],
            "account": r["AccountName"],
            "vat_inclusive": primary,
            # Shown when the two columns disagree - that means something
            # wrote one of them alone, and the app's behaviour is then
            # anybody's guess.
            "mismatch": primary != secondary,
        })
    return {"ok": True, "branches": branches, "message": None}


def set_vat_inclusive(branch_id, value):
    """Turn VAT-inclusive pricing on or off for one branch.

    Returns (ok, message). Writes both columns, in one transaction,
    and refuses to commit unless exactly one row changed.
    """
    try:
        branch_id = int(branch_id)
    except (TypeError, ValueError):
        return False, "branch id must be a number"
    wanted = 1 if value else 0

    db = _db()
    try:
        import pyodbc
        cn = pyodbc.connect(db._conn_str(), autocommit=False)
    except Exception as e:
        return False, "could not reach the database: " + str(e)[:140]

    try:
        cur = cn.cursor()
        cur.execute(
            "UPDATE dbo.Branch SET %s = ?, %s = ? WHERE BranchId = ?"
            % VAT_COLUMNS, [wanted, wanted, branch_id])
        touched = cur.rowcount
        if touched != 1:
            cn.rollback()
            return False, ("expected to change 1 branch, this would change %d - "
                           "nothing was saved" % touched)
        cn.commit()
    except Exception as e:
        try:
            cn.rollback()
        except Exception:
            pass
        return False, "update failed: " + str(e)[:160]
    finally:
        cn.close()

    name = next((b["name"] for b in read().get("branches", [])
                 if b["id"] == branch_id), "branch %d" % branch_id)
    return True, "%s: VAT is now %s the rate" % (
        name, "inside" if wanted else "added on top of")
