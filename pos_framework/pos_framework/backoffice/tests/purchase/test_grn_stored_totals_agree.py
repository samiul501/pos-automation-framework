# ============================================================
# CLIENT ISSUE - the same one, asked of the whole database.
#
# The browser test next door proves one GRN keeps its amount
# through a save. This one asks the question the client actually
# asked - "is this happening to us?" - of every GRN already
# stored, without a browser and in seconds.
#
# Three things have to agree for a GRN to reconcile:
#
#   header ItemTotalAmount  ==  sum of its lines' TotalAmount
#   header NetAmount        ==  item total + VAT - discount + charges
#   each line's TotalAmount ==  Quantity x Price
#
# The third is where the reported symptom would live. A line
# price is stored at 6 decimals but its total at 2, so if the
# save had recomputed from a rounded rate, the line total would
# match Quantity x ROUND(Price, 2) instead of Quantity x Price.
# This test reports which one each disagreeing GRN matches, which
# is the difference between "rounded the rate" and "rounded the
# total".
#
# It is read-only and touches no UI, so it can be pointed at any
# environment - including one with real data - safely.
# ============================================================

import allure
import pytest

from backoffice.support import requires

pytestmark = [pytest.mark.client_issue, pytest.mark.module]

# A GRN is allowed to be off by less than half a paisa: the columns are
# 2-decimal and a sum of rounded parts can land there honestly. Anything
# above this is a real difference someone would have to explain.
TOLERANCE = 0.005

# How many offenders to list before the report gets unhelpful.
SHOW = 25


def _attach(name, body):
    text = body if isinstance(body, str) else str(body)
    print("\n--- %s ---\n%s" % (name, text))
    allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)


@allure.feature("Purchase")
@allure.story("Stored GRN totals agree with their own lines")
@allure.severity(allure.severity_level.CRITICAL)
def test_every_stored_grn_adds_up(profile):
    """Every saved GRN's header still matches the lines under it."""
    requires(profile)
    allure.dynamic.title("Stored GRN totals add up - " + profile.label)

    import db_helpers as db
    if not db.is_available():
        pytest.skip("database not reachable: " + (db.unavailable_reason() or ""))

    scope = db._query("""
        SELECT COUNT(DISTINCT h.PurchaseReceiveId) AS grns,
               COUNT(*) AS lines_total,
               SUM(CASE WHEN l.Price <> ROUND(l.Price, 2) THEN 1 ELSE 0 END) AS prices_over_2dp
        FROM dbo.PurchaseReceive h
        JOIN dbo.PurchaseReceiveLine l ON l.PurchaseReceiveId = h.PurchaseReceiveId
    """)[0]
    _attach("what was checked",
            "%s GRNs, %s lines\n%s of those lines hold a price with more than 2 decimals\n"
            "(a 2-decimal price cannot lose anything to rounding, so those are\n"
            "the only lines where the reported symptom could arise at all)"
            % (scope["grns"], scope["lines_total"], scope["prices_over_2dp"]))

    # ---- 1. does the header match its own lines? ---------------------
    # Counted over everything first: a list capped at SHOW would
    # otherwise read as "25 problems" whether there are 25 or 2,500.
    header_count = db._query("""
        SELECT COUNT(*) AS n FROM (
            SELECT h.PurchaseReceiveId
            FROM dbo.PurchaseReceive h
            JOIN dbo.PurchaseReceiveLine l ON l.PurchaseReceiveId = h.PurchaseReceiveId
            WHERE h.isActive = 1
            GROUP BY h.PurchaseReceiveId, h.ItemTotalAmount
            HAVING ABS(SUM(l.TotalAmount) - h.ItemTotalAmount) > ?
        ) x
    """, [TOLERANCE])[0]["n"]

    line_count = db._query("""
        SELECT COUNT(*) AS n
        FROM dbo.PurchaseReceive h
        JOIN dbo.PurchaseReceiveLine l ON l.PurchaseReceiveId = h.PurchaseReceiveId
        WHERE h.isActive = 1
          AND ABS(l.TotalAmount - ROUND(l.Quantity * l.Price, 2)) > ?
    """, [TOLERANCE])[0]["n"]

    header_vs_lines = db._query("""
        SELECT TOP (?)
            h.PurchaseReceiveCode, h.ReceiveDate, h.SupplierName,
            h.ItemTotalAmount,
            SUM(l.TotalAmount) AS sum_of_lines,
            ROUND(SUM(l.TotalAmount) - h.ItemTotalAmount, 2) AS difference
        FROM dbo.PurchaseReceive h
        JOIN dbo.PurchaseReceiveLine l ON l.PurchaseReceiveId = h.PurchaseReceiveId
        WHERE h.isActive = 1
        GROUP BY h.PurchaseReceiveId, h.PurchaseReceiveCode, h.ReceiveDate,
                 h.SupplierName, h.ItemTotalAmount
        HAVING ABS(SUM(l.TotalAmount) - h.ItemTotalAmount) > ?
        ORDER BY ABS(SUM(l.TotalAmount) - h.ItemTotalAmount) DESC
    """, [SHOW, TOLERANCE])

    if header_vs_lines:
        _attach("GRNs whose header does not match its lines",
                "\n".join("%-16s %s  header %12.2f  lines %12.2f  %+9.2f"
                          % (r["PurchaseReceiveCode"], r["ReceiveDate"],
                             float(r["ItemTotalAmount"] or 0), float(r["sum_of_lines"] or 0),
                             float(r["difference"] or 0)) for r in header_vs_lines))

    # ---- 2. does each line match quantity x price? -------------------
    # Reported both ways, because which one a line matches says where a
    # difference came from.
    line_maths = db._query("""
        SELECT TOP (?)
            h.PurchaseReceiveCode, h.ReceiveDate, l.ItemName,
            l.Quantity, l.Price, l.TotalAmount,
            ROUND(l.Quantity * l.Price, 2)             AS full_precision,
            ROUND(l.Quantity * ROUND(l.Price, 2), 2)   AS rounded_rate
        FROM dbo.PurchaseReceive h
        JOIN dbo.PurchaseReceiveLine l ON l.PurchaseReceiveId = h.PurchaseReceiveId
        WHERE h.isActive = 1
          AND ABS(l.TotalAmount - ROUND(l.Quantity * l.Price, 2)) > ?
        ORDER BY ABS(l.TotalAmount - ROUND(l.Quantity * l.Price, 2)) DESC
    """, [SHOW, TOLERANCE])

    if line_maths:
        rows = []
        for r in line_maths:
            stored = float(r["TotalAmount"] or 0)
            full = float(r["full_precision"] or 0)
            rounded = float(r["rounded_rate"] or 0)
            matches = ("matches the ROUNDED rate" if abs(stored - rounded) <= TOLERANCE
                       else "matches neither")
            rows.append("%-16s %-28s qty %s x %s\n"
                        "                 stored %12.2f | full precision %12.2f | "
                        "rounded rate %12.2f   -> %s"
                        % (r["PurchaseReceiveCode"], str(r["ItemName"])[:28],
                           r["Quantity"], r["Price"], stored, full, rounded, matches))
        _attach("lines whose total is not quantity x price", "\n".join(rows))

    # ---- verdict -----------------------------------------------------
    summary = ("GRNs checked                         : %s\n"
               "lines checked                        : %s\n"
               "headers disagreeing with their lines : %d\n"
               "lines disagreeing with qty x price   : %d"
               % (scope["grns"], scope["lines_total"], header_count, line_count))
    _attach("verdict", summary)

    assert not header_count and not line_count, (
        "stored GRNs do not add up:\n" + summary +
        "\n(the attachments list the worst %d of each)" % SHOW)
