# ============================================================
# CREDIT SALES - one continuous flow, in the order a person
# would do it by hand:
#
#   01  web : create a customer with a credit limit + credit days
#   02  db  : the customer landed with exactly those values
#   03  exe : Sales Collection shows the same four cards
#   04  exe : sell that customer an item on Payment Type = Credit Sales
#   05  db  : the invoice is a credit invoice and the due moved
#   06  exe : Sales Collection updated - cards AND the invoice row
#
# The steps share state through a module-level dict rather than
# fixtures because they are deliberately ORDERED - each one builds
# on the last, and a failure part-way should leave the later steps
# reporting "nothing to check" instead of inventing a customer.
#
# EVERYTHING IS DYNAMIC (explicit instruction): the customer is
# created fresh every run with a mobile number proven unused
# against the database, the item is whatever the database says is
# sellable right now, and every expected number is read back from
# the database - nothing is hardcoded. The first agreed inputs are
# credit limit 5000 / credit days 10 (credit_config.py).
#
# Run from pos_framework/pos_framework:
#   ..\venv\Scripts\python -m pytest credit_tests/test_credit_sales.py --alluredir=allure-results-credit -p no:cacheprovider
# ============================================================

import time

import allure
import pytest
from allure_commons.types import Severity
from playwright.sync_api import sync_playwright

from credit_tests import credit_config as ccfg
from credit_tests import credit_data as cd
from credit_tests import credit_db as cdb
from credit_tests import credit_web as cw
from credit_tests import credit_actions as ca


RUN = {}


def _money(text):
    """'5,000.00' / '120' / None -> float. The exe prints Pending Due as a
    bare '0' when there is nothing owed, so this must not assume decimals."""
    if text is None:
        return None
    cleaned = str(text).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _same(a, b):
    return a is not None and b is not None and abs(a - b) <= ccfg.MONEY_TOLERANCE


def _attach(name, body):
    allure.attach(str(body), name=name, attachment_type=allure.attachment_type.TEXT)


def _need(*keys):
    missing = [k for k in keys if k not in RUN]
    if missing:
        pytest.skip("earlier step did not complete (missing: " + ", ".join(missing) + ")")


# ============ 01: create the customer in the backend ============
@allure.feature("Credit Sales")
@allure.story("Customer setup")
@allure.severity(Severity.BLOCKER)
def test_01_create_credit_customer():
    """Creates the customer through the MENU (Configuration -> Customer
    Profile -> Customer). Reaching /create by URL renders a form with no
    Credit Limit or Credit Days at all - credit_web enforces the menu
    route and fails loudly if the credit fields are missing."""
    if not cdb.available():
        pytest.skip("database not reachable: " + str(cdb.unavailable_reason()))

    spec = cd.new_customer_spec()
    RUN["spec"] = spec
    allure.dynamic.title("01. Create a credit customer - limit %s, credit days %s"
                         % (spec["credit_limit"], spec["credit_days"]))
    _attach("customer spec", spec)

    with sync_playwright() as p:
        browser, page = cw.login(p, headless=True)
        try:
            with allure.step("Configuration -> Customer Profile -> Customer"):
                cw.open_create_customer(page)
            with allure.step("Filling the form (only the required fields + credit limit/days)"):
                message = cw.create_credit_customer(page, spec)
            _attach("toast", message or "(no toast captured)")
            RUN["toast"] = message
        finally:
            browser.close()

    assert message and "success" in message.lower(), \
        "the backend did not confirm the customer was created (toast: %r)" % message


# ============ 02: the database agrees ============
@allure.feature("Credit Sales")
@allure.story("Customer setup")
@allure.severity(Severity.BLOCKER)
def test_02_customer_in_database():
    _need("spec")
    spec = RUN["spec"]
    allure.dynamic.title("02. The customer reached the database with the credit values that were typed")

    customer = None
    for _ in range(6):          # the save is committed a beat after the toast
        customer = cdb.get_customer(spec["mobile"])
        if customer:
            break
        time.sleep(2)

    assert customer, "no customer with mobile %s exists in the database" % spec["mobile"]
    RUN["customer"] = customer
    RUN["partner_id"] = customer["PartnerId"]

    limit = float(customer["CreditLimit"] or 0)
    days = int(customer["PaymentDays"] or 0)
    _attach("database row", customer)

    assert customer["PartnerName"] == spec["name"], \
        "name is %r, expected %r" % (customer["PartnerName"], spec["name"])
    assert _same(limit, float(spec["credit_limit"])), \
        "CreditLimit is %s, expected %s" % (limit, spec["credit_limit"])
    assert days == int(spec["credit_days"]), \
        "PaymentDays (Credit Days) is %s, expected %s" % (days, spec["credit_days"])

    position = cdb.credit_position(customer["PartnerId"])
    RUN["position_before"] = position
    _attach("credit position before any sale", position)
    assert _same(position["pending_due"], 0.0), \
        "a brand-new customer already owes %s" % position["pending_due"]


# ============ 03: the exe shows the same thing ============
@allure.feature("Credit Sales")
@allure.story("Sales Collection")
@allure.severity(Severity.CRITICAL)
def test_03_sales_collection_before_sale():
    """Every card is compared against the database, not against the number
    that was typed - so this also catches the backend storing something
    different from what the form accepted."""
    _need("spec", "partner_id")
    spec, partner_id = RUN["spec"], RUN["partner_id"]
    allure.dynamic.title("03. Sales Collection shows the new customer's credit position")

    with allure.step("Opening the exe and searching the customer"):
        main_win = ca.ensure_logged_in()
        main_win = ca.open_sales_collection(main_win)
        main_win = ca.search_customer(main_win, spec["mobile"])

    cards = ca.read_collection_cards(main_win)
    grid = ca.read_collection_grid(main_win)
    expected = cdb.credit_position(partner_id)
    _attach("exe cards", cards)
    _attach("exe grid", grid)
    _attach("database expects", expected)
    RUN["cards_before"] = cards

    assert cards["Customer Name"] == spec["name"], \
        "exe shows customer %r, expected %r" % (cards["Customer Name"], spec["name"])
    assert cards["Mobile No"] == spec["mobile"], \
        "exe shows mobile %r, expected %r" % (cards["Mobile No"], spec["mobile"])
    assert _same(_money(cards["Credit Limit"]), expected["credit_limit"]), \
        "Credit Limit card is %r, database says %s" % (cards["Credit Limit"], expected["credit_limit"])
    assert _same(_money(cards["Pending Due"]), expected["pending_due"]), \
        "Pending Due card is %r, database says %s" % (cards["Pending Due"], expected["pending_due"])
    assert _same(_money(cards["Remaining Credit"]), expected["remaining_credit"]), \
        "Remaining Credit card is %r, database says %s" % (cards["Remaining Credit"], expected["remaining_credit"])
    assert str(cards["Credit Days"]).strip() == str(expected["credit_days"]), \
        "Credit Days card is %r, database says %s" % (cards["Credit Days"], expected["credit_days"])
    assert grid == [], "a customer with no sales already has %d invoice row(s)" % len(grid)


# ============ 04: sell on credit ============
@allure.feature("Credit Sales")
@allure.story("Credit sale")
@allure.severity(Severity.BLOCKER)
def test_04_sell_on_credit():
    """Payment Type = Credit Sales. select_credit_sales() verifies the combo
    actually took the value: clicking it looks like it worked but leaves it
    unset, and the sale then completes as CASH."""
    _need("spec", "partner_id")
    spec = RUN["spec"]
    item = cd.pick_item(spec["credit_limit"])
    RUN["item"] = item
    allure.dynamic.title("04. Sell on credit - %s (%s)" % (item["ItemName"], item["Barcode"]))
    _attach("item", item)

    main_win = ca.ensure_logged_in()
    with allure.step("Customer + item, Payment Type = Credit Sales, pay"):
        result = ca.sell_on_credit(main_win, spec["mobile"], item["Barcode"])
    _attach("sale result", result)
    RUN["sale"] = result

    assert result["payment_rows"], "no credit payment line was added"
    first = " ".join(result["payment_rows"][0])
    assert ca.CREDIT_SALES_OPTION.lower() in first.lower(), \
        "the payment line is %r - the sale did not go through as a credit sale" % first
    assert result["cart_rows_after"] == 0, \
        "the cart still holds %d row(s) after paying" % result["cart_rows_after"]


# ============ 05: the database recorded a credit sale ============
@allure.feature("Credit Sales")
@allure.story("Credit sale")
@allure.severity(Severity.BLOCKER)
def test_05_invoice_is_a_credit_sale():
    _need("partner_id", "sale")
    partner_id = RUN["partner_id"]
    allure.dynamic.title("05. The invoice is a credit invoice and the due moved by its amount")

    invoice = None
    for _ in range(6):
        invoice = cdb.latest_invoice(partner_id)
        if invoice:
            break
        time.sleep(2)
    assert invoice, "the sale produced no invoice for this customer"
    RUN["invoice"] = invoice
    _attach("invoice", invoice)

    total = _money(RUN["sale"]["grand_total"])
    net = float(invoice["NetAmount"] or 0)
    pending = float(invoice["PendingAmount"] or 0)

    assert invoice["IsCreditSales"], \
        "invoice %s is NOT marked as a credit sale" % invoice["SalesOrderCode"]
    assert _same(net, total), \
        "invoice total is %s, the exe showed %s" % (net, total)
    assert _same(pending, net), \
        "a fresh credit invoice should be fully outstanding: pending %s of %s" % (pending, net)

    before = RUN["position_before"]
    after = cdb.credit_position(partner_id)
    RUN["position_after"] = after
    _attach("credit position after the sale", after)

    assert _same(after["pending_due"], before["pending_due"] + net), \
        "Pending Due went %s -> %s, expected +%s" % (before["pending_due"], after["pending_due"], net)
    assert _same(after["remaining_credit"], before["remaining_credit"] - net), \
        "Remaining Credit went %s -> %s, expected -%s" % (before["remaining_credit"], after["remaining_credit"], net)


# ============ 06: Sales Collection reflects the sale ============
@allure.feature("Credit Sales")
@allure.story("Sales Collection")
@allure.severity(Severity.CRITICAL)
def test_06_sales_collection_after_sale():
    """The point of the whole suite: after a credit sale the screen the
    cashier collects money on must show the new position and the new
    invoice - amount, and a due date of invoice date + credit days."""
    _need("spec", "partner_id", "invoice")
    spec, partner_id, invoice = RUN["spec"], RUN["partner_id"], RUN["invoice"]
    allure.dynamic.title("06. Sales Collection updated after the credit sale")

    main_win = ca.ensure_logged_in()
    main_win = ca.open_sales_collection(main_win)
    main_win = ca.search_customer(main_win, spec["mobile"])

    cards = ca.read_collection_cards(main_win)
    grid = ca.read_collection_grid(main_win)
    expected = cdb.credit_position(partner_id)
    db_rows = cdb.credit_invoices(partner_id)
    _attach("exe cards", cards)
    _attach("exe grid", grid)
    _attach("database expects", {"position": expected, "invoices": db_rows})

    assert _same(_money(cards["Credit Limit"]), expected["credit_limit"]), \
        "Credit Limit card is %r, database says %s" % (cards["Credit Limit"], expected["credit_limit"])
    assert _same(_money(cards["Pending Due"]), expected["pending_due"]), \
        "Pending Due card is %r, database says %s" % (cards["Pending Due"], expected["pending_due"])
    assert _same(_money(cards["Remaining Credit"]), expected["remaining_credit"]), \
        "Remaining Credit card is %r, database says %s" % (cards["Remaining Credit"], expected["remaining_credit"])
    assert str(cards["Credit Days"]).strip() == str(expected["credit_days"]), \
        "Credit Days card is %r, database says %s" % (cards["Credit Days"], expected["credit_days"])

    code = invoice["SalesOrderCode"]
    row = next((r for r in grid if r["invoice_no"] == code), None)
    assert row is not None, \
        "invoice %s is missing from the Sales Collection grid (rows: %r)" % (code, [r["invoice_no"] for r in grid])
    RUN["grid_row"] = row

    assert _same(_money(row["pending_amt"]), float(invoice["PendingAmount"])), \
        "grid Pending Amt is %r, database says %s" % (row["pending_amt"], invoice["PendingAmount"])
    assert _same(_money(row["receive_amt"]), float(invoice["CreditReceiveAmount"] or 0)), \
        "grid Receive Amt is %r, database says %s" % (row["receive_amt"], invoice["CreditReceiveAmount"])

    # Due date = invoice date + credit days. The grid prints m/d/yyyy with a
    # time, so only the date part is compared.
    db_row = next((r for r in db_rows if r["SalesOrderCode"] == code), None)
    if db_row and db_row["due_date"]:
        shown = str(row["due_date"]).split(" ")[0]
        parts = shown.split("/")
        if len(parts) == 3:
            shown_date = "%04d-%02d-%02d" % (int(parts[2]), int(parts[0]), int(parts[1]))
            expected_date = db_row["due_date"].strftime("%Y-%m-%d")
            assert shown_date == expected_date, \
                "grid Due Date is %s, expected invoice date + %s days = %s" \
                % (shown_date, spec["credit_days"], expected_date)

    cd.save({
        "spec": spec, "partner_id": partner_id,
        "invoice": invoice["SalesOrderCode"],
        "position_before": RUN.get("position_before"),
        "position_after": expected,
        "grid_row": row,
    })
