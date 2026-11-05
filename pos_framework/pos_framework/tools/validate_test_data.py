# ============================================================
# TEST DATA VALIDATOR - checks every hardcoded barcode, customer
# number and offer dependency in config.py / negative_config.py
# against the live database, and prints what has gone stale.
#
# Run this BEFORE a suite (it takes seconds) instead of finding
# out from a 30-minute UI run that one barcode was deactivated:
#
#   python tools/validate_test_data.py
#
# Exit code 0 = all test data is currently valid, 1 = something
# needs attention. Read-only: it never changes app data.
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import db_helpers as db
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "negative_tests"))
import negative_config as nc


problems = []
warnings = []


def _check_item(code, where):
    item = db.find_item(code)
    if item is None:
        problems.append(where + ": barcode/code '" + code + "' does not exist in the catalogue at all")
        return
    if not item["IsActive"]:
        problems.append(
            where + ": '" + code + "' (" + item["ItemName"] + ") is INACTIVE - the app adds nothing "
            "to the cart for it, with no error popup"
        )
        return
    matched_on = "Barcode" if item["Barcode"] == code else "ItemCode"
    print("    OK  " + code.ljust(14) + " -> " + item["ItemName"][:34].ljust(36) +
          str(item["Price"]).rjust(9) + "   (via " + matched_on + ", " + str(item["BranchName"]) + ")")


def _check_customer(mobile, where):
    rows = db.find_customers(mobile)
    if not rows:
        problems.append(where + ": customer '" + mobile + "' does not exist")
        return
    active = [r for r in rows if r["IsActive"]]
    if not active:
        problems.append(where + ": customer '" + mobile + "' exists but every record is INACTIVE")
        return
    if len(active) > 1:
        names = ", ".join(r["PartnerName"] + " (id " + str(r["PartnerId"]) + ")" for r in active)
        warnings.append(
            where + ": '" + mobile + "' matches " + str(len(active)) + " active customers - " + names +
            ". Which one the POS picks decides whether a group discount applies, so this is a flakiness risk."
        )
        print("    WARN " + mobile.ljust(14) + " -> " + str(len(active)) + " duplicates: " + names[:60])
        return
    print("    OK  " + mobile.ljust(14) + " -> " + active[0]["PartnerName"])


def main():
    print("=" * 78)
    print("POS TEST DATA VALIDATION (read-only)")
    print("=" * 78)

    if not db.is_available():
        print("\nDatabase not reachable - cannot validate.")
        print("Reason: " + str(db.unavailable_reason())[:200])
        return 1

    print("\n[1] config.py - transaction items")
    seen = []
    for txn in config.TRANSACTIONS:
        for code in txn["items"]:
            if code not in seen:
                seen.append(code)
                _check_item(code, "config.TRANSACTIONS")

    print("\n[2] config.py - Hold & Recall items")
    for code in config.HOLD_RECALL_TRANSACTION["items"]:
        if code not in seen:
            seen.append(code)
            _check_item(code, "config.HOLD_RECALL_TRANSACTION")

    print("\n[3] config.py - Exchange replacement items")
    for code in config.EXCHANGE_TRANSACTION["new_item_barcodes"]:
        if code not in seen:
            seen.append(code)
            _check_item(code, "config.EXCHANGE_TRANSACTION")

    print("\n[4] config.py - customers")
    seen_customers = []
    for txn in config.TRANSACTIONS + [config.HOLD_RECALL_TRANSACTION]:
        if txn["customer"] not in seen_customers:
            seen_customers.append(txn["customer"])
            _check_customer(txn["customer"], "config.TRANSACTIONS")

    print("\n[5] negative_config.py - discount test data")
    for code in (nc.DISCOUNT_ITEM_A, nc.DISCOUNT_ITEM_B):
        _check_item(code, "negative_config discount items")
    for mobile in (nc.DISCOUNT_GROUP_CUSTOMER, nc.OTHER_GROUP_CUSTOMER):
        _check_customer(mobile, "negative_config discount customers")

    print("\n[6] negative_config.py - invalid data must STAY invalid")
    bad_item = nc.TRANSACTION_ITEM_NEGATIVE_CASES[0]["item_barcode"]
    if db.find_item(bad_item) is not None:
        problems.append(
            "negative_config: '" + bad_item + "' is supposed to be a NON-EXISTENT barcode, but it now "
            "exists - that negative test silently stops testing anything and still passes"
        )
    else:
        print("    OK  " + bad_item.ljust(14) + " -> still not in the catalogue (good)")

    bad_customer = nc.TRANSACTION_CUSTOMER_NEGATIVE_CASES[0]["customer"]
    if db.find_customers(bad_customer):
        problems.append(
            "negative_config: '" + bad_customer + "' is supposed to be an INVALID customer, but it now exists"
        )
    else:
        print("    OK  " + bad_customer.ljust(14) + " -> still not a registered customer (good)")

    print("\n[7] Manual F4 'Open' offer - needed by the offer tests")
    offers = db.get_active_open_discounts()
    if not offers:
        problems.append(
            "No active 'Open' special discount is in date range today - pos_actions.do_offer_flow() "
            "cannot work, so every offer test will fail for a data reason, not an app bug"
        )
    else:
        for o in offers[:4]:
            print("    OK  " + str(o["OfferName"]).ljust(14) + " -> valid until " + str(o["EndDate"]))
        soonest = min(str(o["EndDate"]) for o in offers)
        warnings.append("The manual 'Open' offer expires on " + soonest + " - offer tests break after that date.")

    print("\n[8] Customer-group discount - still applied in real sales?")
    last = db.get_last_group_discount_for_item(nc.DISCOUNT_ITEM_A, nc.DISCOUNT_GROUP_CUSTOMER)
    if last is None:
        warnings.append("No past sale of " + nc.DISCOUNT_ITEM_A + " to " + nc.DISCOUNT_GROUP_CUSTOMER + " to compare against.")
    elif float(last["LineDiscount"]) <= 0:
        problems.append(
            "The group discount on " + nc.DISCOUNT_ITEM_A + " appears to be gone - the last real sale "
            "(" + str(last["SalesOrderCode"]) + ") applied no line discount"
        )
    else:
        print("    OK  last real sale " + str(last["SalesOrderCode"]) + " on " + str(last["OrderDate"]) +
              " applied a " + str(last["LineDiscount"]) + "% line discount")

    print("\n" + "=" * 78)
    if warnings:
        print("WARNINGS (" + str(len(warnings)) + ")")
        for w in warnings:
            print("  ! " + w)
    if problems:
        print("\nPROBLEMS (" + str(len(problems)) + ") - fix these before running the suite")
        for p in problems:
            print("  X " + p)
        print("=" * 78)
        return 1
    print("\nAll test data is valid right now.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        db.close()
