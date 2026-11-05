# ============================================================
# CONFIG FILE - only open this file to change data/settings
# ============================================================

import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    """Read .env next to this file into the environment.

    Credentials live there, never here - this file is committed. Missing
    values are left empty rather than raised on, so the suites can still be
    collected on a machine without a .env (CI does exactly that).
    """
    path = os.path.join(_HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

# ---- App Launch Info ----
# APP_NAME is looked up dynamically at launch time (via Get-StartApps) so
# reinstalling/updating the app doesn't break automation even though its
# underlying package identity changes with each build. APP_ID below is
# only a fallback for if that lookup ever fails.
APP_NAME = "POSAPP"
APP_ID = "<YourAppPackageFamilyName>!App"

# ---- Login Credentials ----
# These come from .env (see .env.example). Never write them here - this
# file is committed, .env is not.
USER_ID = os.getenv("POS_USER_ID", "")
PASSWORD = os.getenv("POS_PASSWORD", "")

# ---- Normal Transactions (6) ----
# Transaction 2 verifies the "Pos Group" customer-group discount set up in
# the POSAPP admin panel (Discount & Offer setup, active 2026-08-12 to
# 2026-08-19 - recheck/recreate the offer there and refresh these expected
# values if it lapses). "01700000004" (VIP Customer) is in that group;
# expected_discounted_total/expected_total_discount are the exact
# GrandTotal/TextBoxTotalDiscount values read live off the POS screen for
# these items - if a new app build changes the discount setup or item
# prices, these will no longer match and the transaction test fails.
#
# "A0104000001" was removed (2026-08-16) - verified live it can no longer
# be added to the cart at all (silently not found, no error popup) even
# though it's a valid-looking barcode; likely removed/renamed in the item
# catalog. This is what was actually causing the discount mismatch
# (expected 1561/79.50 for 3 items, but only 2 items' worth ever landed in
# the cart) - not a lapsed discount as originally guessed. Re-verified
# live with just the 2 remaining items: GrandTotal 1511, TotalDiscount 79.50.
TRANSACTIONS = [
    {"customer": "01700000005", "items": ["1010", "1011"], "offer": None},
    {
        "customer": "01700000004",
        "items": ["4041", "4040"],
        "offer": None,
        "expected_discounted_total": "1511",
        "expected_total_discount": "79.50",
    },
    {"customer": "01700000006", "items": ["3031", "4040", "4042"], "offer": None},
    {"customer": "01700000007", "items": ["4040"], "offer": None},
    {"customer": "01700000008", "items": ["4040", "3032"], "offer": None},
    {"customer": "01700000009", "items": ["4040"], "offer": {"discount_type": "Percentage", "discount_value": "10"}},
]

# ---- Hold + Recall Transaction ----
HOLD_RECALL_TRANSACTION = {
    "customer": "0175051961",
    "items": ["1010", "1011","3031", "3032", "3033", "3034", "4041", "4042"],
}

# ---- Exchange Transaction ----
# invoice_no is captured automatically at runtime from the Hold & Recall
# transaction's invoice (see test_pos_full.py), so it is always fresh.
EXCHANGE_TRANSACTION = {
    "new_item_barcodes": ["4040", "4041"],  # replacement product with equal or higher price than the exchanged item
}

# ---- Return Transaction ----
# invoice_no is captured automatically at Return time by picking the
# highest-quantity invoice on the Invoice Page (see test_pos_full.py).

# ---- Backend Web Report (verifies exe transactions land correctly) ----
# This login is distinct from the exe's own USER_ID/PASSWORD above - it is
# a separate backend web account. A wrong mobile number here silently logs
# into a different/empty-permission account rather than failing outright,
# so double check this value first if the web report ever comes back
# empty (see memory/web_report_verification.md).
WEB_BASE_URL = "https://demo-backoffice.example.com/"
WEB_MOBILE = os.getenv("WEB_MOBILE", "")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")

# Handoff file: test_pos_full.py captures each transaction's invoice
# number/expected GrandTotal here; test_web_report_verification.py reads
# it after the exe closes. A file handoff since the two test files run as
# separate pytest sessions with no shared in-process state.
WEB_VERIFY_DATA_FILE = "web_verify_data.json"
