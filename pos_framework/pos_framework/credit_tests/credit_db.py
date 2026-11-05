# ============================================================
# CREDIT DB - read-only database lookups for the credit-sales
# flow. Reuses the parent db_helpers connection (and its
# SELECT-only guard); nothing here writes.
#
# THE CREDIT MODEL, read live out of DemoStore on 2026-09-22
# and checked against the exe's own Sales Collection screen for
# customer 01700000009 (limit 10000, due 1110, remaining 8890,
# credit days 10 - every number below reproduced it exactly):
#
#   dbo.Partner.CreditLimit        -> the "Credit Limit" card
#   dbo.Partner.PaymentDays        -> the "Credit Days" card
#                                     (the form labels it Credit Days)
#   dbo.Partner.IsMonthly          -> the Is Monthly checkbox
#   dbo.Partner.Tolerance          -> Tolerance(%)
#
#   A credit sale is pos.POSSalesDeliveryHeader with
#   IsCreditSales = 1. Its money columns:
#       NetAmount           the invoice total
#       PendingAmount       what is still owed on THAT invoice
#       CreditReceiveAmount what has been collected against it
#
#   Pending Due      = SUM(PendingAmount) over the customer's
#                      invoices with PendingAmount > 0
#   Remaining Credit = CreditLimit - Pending Due
#   Due Date         = OrderDate + PaymentDays   (4/28 + 10 = 5/8,
#                      exactly what the exe's grid showed)
# ============================================================

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_helpers as db

from credit_tests import credit_config as ccfg


def available():
    return db.is_available()


def unavailable_reason():
    return db.unavailable_reason()


# ---- the customer ---------------------------------------------------

def get_customer(mobile_no):
    """The customer row the POS cares about: PartnerTypeId = 1 only.
    Returns None when the number is not a customer (yet).

    PartnerTypeId matters - the same mobile number can also exist as a
    supplier (2) or loan employee (6), and those rows carry their own
    CreditLimit that has nothing to do with the till."""
    rows = db._query(
        "SELECT PartnerId, PartnerName, MobileNo, PartnerTypeId, CreditLimit, PaymentDays, "
        "IsMonthly, Tolerance, IsCreditLimitForAllOutlet, IsActive, PartnerGroupId "
        "FROM dbo.Partner WHERE MobileNo = ? AND PartnerTypeId = 1",
        [mobile_no],
    )
    return rows[0] if rows else None


def customer_exists(mobile_no):
    """Any partner type - used to prove a generated number is free."""
    return bool(db._query("SELECT TOP 1 PartnerId FROM dbo.Partner WHERE MobileNo = ?", [mobile_no]))


def unused_mobile_no():
    """A mobile number no partner of ANY type uses yet, so each run
    creates a genuinely new customer instead of colliding with an
    earlier one (the exe treats a duplicate number as ambiguous)."""
    import time
    candidate = "0198" + str(int(time.time()))[-7:]
    while customer_exists(candidate):
        candidate = str(int(candidate) + 1).zfill(len(candidate))
    return candidate


# ---- the credit position -------------------------------------------

def credit_position(partner_id):
    """What the exe's four cards should show, computed from the database.

    Returns {credit_limit, pending_due, remaining_credit, credit_days}
    as floats/ints, or None if the customer is gone."""
    rows = db._query(
        "SELECT CreditLimit, PaymentDays FROM dbo.Partner WHERE PartnerId = ? AND PartnerTypeId = 1",
        [partner_id],
    )
    if not rows:
        return None
    limit = float(rows[0]["CreditLimit"] or 0)
    days = int(rows[0]["PaymentDays"] or 0)
    due = float(db._query(
        "SELECT ISNULL(SUM(PendingAmount), 0) AS due FROM pos.POSSalesDeliveryHeader "
        "WHERE CustomerId = ? AND PendingAmount > 0",
        [partner_id],
    )[0]["due"])
    return {
        "credit_limit": limit,
        "pending_due": due,
        "remaining_credit": limit - due,
        "credit_days": days,
    }


def credit_invoices(partner_id):
    """Every outstanding credit invoice for this customer, oldest first -
    the same rows the Sales Collection grid lists. `due_date` is derived
    here (OrderDate + PaymentDays) because the header does not store it."""
    rows = db._query(
        "SELECT h.SalesOrderId, h.SalesOrderCode, h.OrderDate, h.NetAmount, h.ReceiveAmount, "
        "       h.PendingAmount, h.CreditReceiveAmount, h.TotalQuantity, h.IsCreditSales, "
        "       h.CounterId, h.OfficeId, p.PaymentDays "
        "FROM pos.POSSalesDeliveryHeader h "
        "JOIN dbo.Partner p ON p.PartnerId = h.CustomerId "
        "WHERE h.CustomerId = ? AND h.PendingAmount > 0 "
        "ORDER BY h.SalesOrderId",
        [partner_id],
    )
    for r in rows:
        order_date = r["OrderDate"]
        days = int(r["PaymentDays"] or 0)
        if isinstance(order_date, (datetime.date, datetime.datetime)):
            r["due_date"] = order_date + datetime.timedelta(days=days)
        else:
            r["due_date"] = None
    return rows


def latest_invoice(partner_id):
    """The customer's newest invoice of any kind - used right after a sale
    to pin down exactly which invoice the exe just created."""
    rows = db._query(
        "SELECT TOP 1 SalesOrderId, SalesOrderCode, OrderDate, NetAmount, ReceiveAmount, "
        "       PendingAmount, CreditReceiveAmount, IsCreditSales, IsComplete, TotalQuantity, "
        "       CounterId, OfficeId "
        "FROM pos.POSSalesDeliveryHeader WHERE CustomerId = ? ORDER BY SalesOrderId DESC",
        [partner_id],
    )
    return rows[0] if rows else None


def invoice_by_code(code):
    rows = db._query(
        "SELECT SalesOrderId, SalesOrderCode, CustomerId, CustomerName, OrderDate, NetAmount, "
        "       ReceiveAmount, PendingAmount, CreditReceiveAmount, IsCreditSales, IsComplete "
        "FROM pos.POSSalesDeliveryHeader WHERE SalesOrderCode = ?",
        [code],
    )
    return rows[0] if rows else None


# ---- what to sell ---------------------------------------------------

def sellable_item(max_price=None):
    """One item the till can actually sell, chosen at run time rather than
    hardcoded - db_helpers.find_sellable_items() already encodes the
    warehouse rule and the weighing-scale barcode trap."""
    items = db.find_sellable_items(count=1, max_price=max_price)
    return items[0] if items else None
