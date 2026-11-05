# ============================================================
# DATABASE HELPERS - READ-ONLY access to the DemoStore SQL
# Server that backs the POS exe. Mirrors pos_helpers.py's role:
# generic, reusable lookups only - no assertions, no business
# expectations. Those belong in the test files.
#
# WHY THIS EXISTS
# ---------------
# config.py / negative_config.py hardcode barcodes, customer
# numbers and expected totals. Those go stale silently: an item
# gets deactivated, a customer is duplicated, an offer lapses -
# and the test then fails in a way that looks like an app bug.
# This module lets the tests ask the database what is actually
# valid RIGHT NOW instead of trusting a hardcoded guess.
#
# SAFETY
# ------
# Every connection is opened read-only AND every statement is
# checked to start with SELECT/WITH before it runs (see _query).
# Tests must never write to this database - test data is created
# through the POS UI, the way a real cashier would, so that what
# is verified is real app behaviour and not a row this framework
# inserted itself.
#
# OPTIONAL BY DESIGN
# ------------------
# The database is not reachable from every machine that runs
# these tests. Nothing here raises on import, and is_available()
# lets a caller degrade gracefully (skip, don't fail) when there
# is no connection.
# ============================================================

import os
import time

_DRIVER_IMPORT_ERROR = None
try:
    import pyodbc
except ImportError as e:          # pyodbc is optional - see module docstring
    pyodbc = None
    _DRIVER_IMPORT_ERROR = e


# ---- .env loading -------------------------------------------------
# A tiny loader instead of the python-dotenv package: this project
# deliberately keeps its dependency list short, and all that is
# needed is "KEY=VALUE per line, # for comments".

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env():
    if not os.path.exists(_ENV_FILE):
        return
    with open(_ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            # Real environment variables win over the file, so CI can
            # override without editing anything on disk.
            os.environ.setdefault(key.strip(), value.strip())


_load_env()


def _conn_str():
    return (
        "DRIVER={" + os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server") + "};"
        "SERVER=" + os.getenv("DB_SERVER", "") + ";"
        "DATABASE=" + os.getenv("DB_NAME", "DemoStore") + ";"
        "UID=" + os.getenv("DB_USER", "") + ";"
        "PWD=" + os.getenv("DB_PASSWORD", "") + ";"
        "Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=15"
    )


# ---- connection ---------------------------------------------------

_connection = None
_unavailable_reason = None


def _get_connection():
    """One connection reused for the whole session - opening a new
    one per lookup costs ~1s against this server, and a test run does
    dozens of lookups."""
    global _connection
    if _connection is not None:
        return _connection
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed (" + str(_DRIVER_IMPORT_ERROR) + ")")
    _connection = pyodbc.connect(_conn_str(), readonly=True, autocommit=True)
    return _connection


def is_available():
    """True if the database can actually be queried. Callers should
    use this to SKIP database-backed checks rather than fail them -
    a developer without network access to the DB server must still
    be able to run the UI suites."""
    global _unavailable_reason
    try:
        _query("SELECT 1 AS ok")
        return True
    except Exception as e:
        _unavailable_reason = str(e)
        return False


def unavailable_reason():
    return _unavailable_reason


def close():
    global _connection
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None


# ---- query plumbing -----------------------------------------------

def _query(sql, params=None):
    """Run a SELECT and return a list of dicts.

    Refuses anything that is not a SELECT/WITH. This is defence in
    depth, not the only protection (the connection is opened
    read-only too) - a typo or a careless edit must never be able to
    modify the live POS database from a test run."""
    stripped = sql.strip().lstrip("(").lstrip()
    if not stripped[:6].upper().startswith(("SELECT", "WITH")):
        raise ValueError("db_helpers only runs SELECT queries, refused: " + sql[:60])

    cursor = _get_connection().cursor()
    cursor.execute(sql, params or [])
    columns = [c[0] for c in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    return rows


def query(sql, params=None):
    """Public escape hatch for one-off exploratory SELECTs."""
    return _query(sql, params)


# ---- items --------------------------------------------------------
# The POS item search box resolves a typed value against BOTH
# Item.Barcode AND Item.ItemCode - confirmed live from real invoice
# lines: "4040" matched Barcode (Boal Fish, Mirpur-13) while "3031"
# matched ItemCode (Rui Fish, Demo Super Shop). Any lookup that
# only checks Barcode will wrongly report half the test data as
# missing, so both columns are always checked here.

_ITEM_COLUMNS = """
    ItemId, ItemName, ItemCode, Barcode, CurrentSellingPrice AS Price,
    IsActive, BranchName, ItemCategoryName
"""


def find_item(code):
    """Resolve one typed barcode/item-code the way the POS does.
    Returns the matching row, or None if nothing matches at all.

    When several rows match (the same barcode exists per branch -
    e.g. "3030" is Beef Bone Full @781 in Mirpur-13 but also an
    inactive Test Item @1992 in DEMO_STORE), an ACTIVE row is
    always preferred, since an inactive item is silently not added
    to the cart by the app."""
    rows = _query(
        "SELECT " + _ITEM_COLUMNS + " FROM dbo.Item WHERE Barcode = ? OR ItemCode = ? "
        "ORDER BY CASE WHEN IsActive = 1 THEN 0 ELSE 1 END, ItemId",
        [code, code]
    )
    return rows[0] if rows else None


def is_item_sellable(code):
    """True only if a typed code resolves to an ACTIVE item.

    This is the check that would have saved a long investigation:
    barcode "A0104000001" (Salt-1) looks perfectly valid but has
    IsActive = 0, and the app adds nothing to the cart for it - with
    no error popup at all. That silent no-op was originally
    misdiagnosed as a lapsed discount (see config.py's own notes)."""
    item = find_item(code)
    return bool(item and item["IsActive"])


def find_sellable_items(count=2, min_price=None, max_price=None, branch=None):
    """Pick `count` items that are guaranteed addable to the cart
    right now - active, priced, and (by default) proven by having
    actually been sold through the POS before, which rules out items
    that exist in the catalogue but cannot be transacted.

    Each returned item has a DISTINCT barcode. That matters more
    than it looks: different items legitimately share one barcode
    here (e.g. "122DE" is both "Chipsx3-White" and "Chipsx3-Red"),
    and the POS resolves a typed barcode to a single item - so
    scanning a repeated barcode bumps that line's quantity instead
    of adding a new line. Without this de-duplication, asking for
    100 items would silently produce a 98-line cart and any
    row-count assertion would fail for a data reason, not a bug."""
    # The inner query aliases CurrentSellingPrice to Price, so the
    # outer one must select the aliased names, not the raw columns.
    outer_columns = "d.ItemId, d.ItemName, d.ItemCode, d.Barcode, d.Price, d.IsActive, d.BranchName, d.ItemCategoryName"
    sql = (
        "SELECT TOP (?) " + outer_columns + " FROM ("
        "  SELECT " + _ITEM_COLUMNS + ", "
        "         ROW_NUMBER() OVER (PARTITION BY i.Barcode ORDER BY i.ItemId DESC) AS rn "
        "  FROM dbo.Item i "
        "  WHERE i.IsActive = 1 AND i.CurrentSellingPrice > 0 AND i.Barcode IS NOT NULL "
        "  AND EXISTS (SELECT 1 FROM pos.POSSalesDeliveryLine l WHERE l.ItemId = i.ItemId) "
    )
    params = [count]
    if min_price is not None:
        sql += "  AND i.CurrentSellingPrice >= ? "
        params.append(min_price)
    if max_price is not None:
        sql += "  AND i.CurrentSellingPrice <= ? "
        params.append(max_price)
    if branch is not None:
        sql += "  AND i.BranchName = ? "
        params.append(branch)
    sql += ") d WHERE d.rn = 1 ORDER BY d.ItemId DESC"
    return _query(sql, params)


def find_unused_barcode():
    """Return a barcode string that matches NO item, for negative
    tests. Better than a hardcoded "88888888888": if someone ever
    creates an item with that barcode, the hardcoded negative test
    silently stops testing anything, and still passes."""
    candidate = "99" + str(int(time.time()))
    while find_item(candidate) is not None:
        candidate += "9"
    return candidate


# ---- customers ----------------------------------------------------

# dbo.Partner is NOT a customer table - it holds every kind of
# business partner: 41796 Customers, 2078 Suppliers, 392 Loan
# Employees and a few others (confirmed live). Every lookup here
# therefore filters PartnerTypeId = 1, or it would happily hand a
# supplier's mobile number back as a "customer" and the POS would
# reject it at the till for reasons no one could see from the test.
_CUSTOMER_TYPE_ID = 1


def find_customers(mobile_no, customers_only=True):
    """All partners registered under one mobile number.

    Deliberately returns a LIST, not a single row: this database has
    real duplicates (e.g. "01700000010" is both "Alex" and "mahin";
    "01700000007" is both "Samiul1" and "rereresr"). Which one the
    POS picks decides whether a customer-group discount applies, so
    a duplicate is a genuine flakiness risk that a caller should be
    able to see rather than have hidden behind a TOP 1.

    Pass customers_only=False to include suppliers/employees too -
    useful when checking that a number is unused by ANY partner."""
    sql = (
        "SELECT PartnerId, PartnerName, MobileNo, IsActive, PartnerTypeId, PartnerTypeName "
        "FROM dbo.Partner WHERE MobileNo = ? "
    )
    params = [mobile_no]
    if customers_only:
        sql += "AND PartnerTypeId = ? "
        params.append(_CUSTOMER_TYPE_ID)
    sql += "ORDER BY PartnerId"
    return _query(sql, params)


def find_active_customer_numbers(count=5):
    """Mobile numbers that map to exactly ONE active CUSTOMER - i.e.
    safe to use as test customers, with no duplicate ambiguity and
    no risk of picking up a supplier."""
    rows = _query(
        "SELECT TOP (?) MobileNo FROM dbo.Partner "
        "WHERE IsActive = 1 AND PartnerTypeId = ? "
        "AND MobileNo IS NOT NULL AND LEN(MobileNo) >= 11 "
        "GROUP BY MobileNo HAVING COUNT(*) = 1 ORDER BY MAX(PartnerId) DESC",
        [count, _CUSTOMER_TYPE_ID]
    )
    return [r["MobileNo"] for r in rows]


def find_unused_customer_number():
    """A mobile number no partner uses, for the invalid-customer
    negative case - same rationale as find_unused_barcode().
    Checks ALL partner types, not just customers: a supplier's
    number is still "taken" as far as the POS is concerned."""
    candidate = "0199" + str(int(time.time()))[-7:]
    while find_customers(candidate, customers_only=False):
        candidate += "9"
    return candidate


# ---- invoices -----------------------------------------------------
# These are the third source of truth. The framework already checks
# the exe screen against the backend web report; reading the invoice
# straight out of the database pins down WHICH of the two is wrong
# when they disagree.

def get_invoice(invoice_no):
    """Header totals for one invoice, or None if it does not exist."""
    rows = _query(
        "SELECT SalesOrderId, SalesOrderCode, BranchName, CustomerName, Phone, OrderDate, "
        "TotalQuantity, ItemTotalAmount, NetDiscount, TotalVat, NetAmount, ReceiveAmount "
        "FROM pos.POSSalesDeliveryHeader WHERE SalesOrderCode = ?",
        [invoice_no]
    )
    return rows[0] if rows else None


def get_invoice_lines(invoice_no):
    """Every sold line of one invoice, with the item identity joined
    back in - so a test can assert that the items it TYPED are the
    items that were actually SOLD, which the UI alone cannot prove."""
    return _query(
        "SELECT l.ItemId, l.ItemName, i.Barcode, i.ItemCode, i.BranchName, "
        "l.Quantity, l.Price, l.LineDiscount, l.OtherDiscount, l.VatAmount, l.NetAmount "
        "FROM pos.POSSalesDeliveryLine l "
        "JOIN pos.POSSalesDeliveryHeader h ON l.SalesOrderId = h.SalesOrderId "
        "LEFT JOIN dbo.Item i ON i.ItemId = l.ItemId "
        "WHERE h.SalesOrderCode = ? ORDER BY l.Id",
        [invoice_no]
    )


def find_returnable_invoice(min_quantity=2):
    """Newest genuine SALE invoice with enough quantity to exercise
    Exchange / Return. Replaces walking the Invoice Page grid in the
    UI (pos_helpers.get_latest_invoice_no), which has to navigate two
    screens and guess from a rendered quantity column.

    IMPORTANT - what this does NOT tell you: whether the invoice has
    already been partly or fully returned. Three columns look like
    they should answer that, and none of them does:
      - `ReturnAmount` is set ON THE RETURN transaction itself, not
        on the original sale, and 66329 of 112335 headers carry a
        non-zero value - it is not a "has been returned" flag.
      - `SalesOrderRefId` is 0 on every single row, so there is no
        header-level link from a return back to its original sale.
      - `SalesOrReturn` reads "Sales" even on return transactions.
    So the caller must still confirm remaining quantity through the
    Return popup itself (which the app does enforce - see
    negative_config.RETURN_QUANTITY_VALIDATION_CASE). Returns and
    exchanges are excluded here via ISReturn/ISExchange, which ARE
    reliable, plus NetAmount > 0."""
    rows = _query(
        "SELECT TOP 1 SalesOrderCode, OrderDate, TotalQuantity, NetAmount "
        "FROM pos.POSSalesDeliveryHeader "
        "WHERE TotalQuantity >= ? AND NetAmount > 0 "
        "AND ISNULL(ISReturn, 0) = 0 AND ISNULL(ISExchange, 0) = 0 "
        "ORDER BY SalesOrderId DESC",
        [min_quantity]
    )
    return rows[0] if rows else None


# ---- discounts / offers -------------------------------------------

def get_active_open_discounts():
    """The manual F4 "Open" (formerly labelled "Cost Guard") special
    discounts that are in date range today.

    pos_actions.do_offer_flow() picks the list entry titled "Open",
    so if this comes back empty the offer step cannot work and any
    offer test should be skipped as un-runnable rather than reported
    as an app failure."""
    return _query(
        "SELECT HeaderId, OfferName, DiscountType, Value, "
        "CAST(StartDate AS date) AS StartDate, CAST(EndDate AS date) AS EndDate, "
        "IsOpenDiscount, IsCostGuardEnable "
        "FROM pos.POSSpecialDiscount "
        "WHERE IsActive = 1 AND IsOpenDiscount = 1 "
        "AND CAST(GETDATE() AS date) BETWEEN CAST(StartDate AS date) AND CAST(EndDate AS date) "
        "ORDER BY HeaderId DESC"
    )


def get_last_group_discount_for_item(barcode, mobile_no):
    """The most recent REAL sale of this item to this customer, with
    the line discount the app actually applied.

    Used to confirm a customer-group discount is still live before
    asserting an exact expected total. The group-discount setup is
    spread across several admin tables and the POS resolves it at
    sale time, so the last actual sale is the trustworthy signal -
    not a setup row that may or may not still be the one in force."""
    rows = _query(
        "SELECT TOP 1 h.SalesOrderCode, h.OrderDate, l.Price, l.LineDiscount, "
        "l.OtherDiscount, l.NetAmount, h.NetAmount AS InvoiceNetAmount "
        "FROM pos.POSSalesDeliveryLine l "
        "JOIN pos.POSSalesDeliveryHeader h ON l.SalesOrderId = h.SalesOrderId "
        "JOIN dbo.Item i ON i.ItemId = l.ItemId "
        "WHERE (i.Barcode = ? OR i.ItemCode = ?) AND h.Phone = ? "
        "ORDER BY h.SalesOrderId DESC",
        [barcode, barcode, mobile_no]
    )
    return rows[0] if rows else None
