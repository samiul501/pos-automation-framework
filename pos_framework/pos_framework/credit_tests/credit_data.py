# ============================================================
# CREDIT DATA - what a run is made of, decided at run time.
#
# The suite must not depend on a customer somebody created by
# hand: those drift (their due changes, they get deactivated,
# their limit is edited) and the test then fails for data reasons
# that look like app bugs. So every run mints its own customer
# with a mobile number proven free against the database, and the
# item to sell is whatever the database says is genuinely
# sellable right now.
#
# The run is also written to disk (last_run.json) so a failure can
# be re-examined - which customer, which limit, which invoice -
# without re-reading the whole Allure report.
# ============================================================

import os
import json
import random
import datetime

from credit_tests import credit_config as ccfg
from credit_tests import credit_db as cdb


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_run.json")


def new_customer_spec(credit_limit=None, credit_days=None):
    """A customer this run will create. `credit_limit`/`credit_days`
    default to the agreed 5000 / 10; pass None-and-set-RANDOM to vary
    them (see random_spec)."""
    stamp = datetime.datetime.now().strftime("%y%m%d%H%M%S")
    return {
        "name": ccfg.CUSTOMER_NAME_PREFIX + "-" + stamp,
        "mobile": cdb.unused_mobile_no(),
        "office": ccfg.OFFICE_NAME,
        "territory": ccfg.TERRITORY_OPTION,
        "customer_point": ccfg.CUSTOMER_POINT_OPTION,
        "credit_limit": ccfg.DEFAULT_CREDIT_LIMIT if credit_limit is None else credit_limit,
        "credit_days": ccfg.DEFAULT_CREDIT_DAYS if credit_days is None else credit_days,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def random_spec():
    """A spec with the limit and days drawn from the configured choices -
    for runs that should not always exercise the same numbers."""
    return new_customer_spec(
        credit_limit=random.choice(ccfg.CREDIT_LIMIT_CHOICES),
        credit_days=random.choice(ccfg.CREDIT_DAYS_CHOICES),
    )


def pick_item(credit_limit):
    """An item whose price fits inside the credit limit, so one credit
    sale can never breach the limit by accident (the limit-breach case is
    a deliberate test of its own, not a side effect of item choice)."""
    max_price = max(50, int(credit_limit) // 4)
    item = cdb.sellable_item(max_price=max_price)
    if item is None:
        item = cdb.sellable_item()
    if item is None:
        raise AssertionError("the database has no sellable item right now - cannot run a credit sale")
    return item


def save(state):
    state = dict(state)
    state["saved_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
    return STATE_FILE


def load():
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)
