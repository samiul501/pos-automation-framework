# ============================================================
# CLIENT ISSUE - the same one, at the size it was reported.
#
# The single-line test next door proves the arithmetic survives
# a save. It has to: with one clean line there is nothing for a
# rounding step to lose. The outlets reported this on real
# invoices - a dozen or more lines, different rates, different
# VAT percentages - and that is where it shows.
#
# It already has. At fifteen lines the create screen showed
# 174,379.95 and the saved GRN held 174,379.93, while every
# individual line was exact to the paisa. The error is not in
# any line; it is in how the header discount is taken off the
# total, and it GROWS WITH THE NUMBER OF LINES:
#
#     1 line   0.00        14 lines  0.01        15 lines  0.02
#
# So this file runs two sizes:
#
#   "client invoice"  15 lines, the client's own rates and VAT mix
#   "heavy"           30 lines, every quantity over 100, every rate
#                     over 100 taka and fractional, fractional VAT
#                     and a fractional discount - the shape that
#                     makes the drift largest
#
# Both then read the GRN in all four places it can be seen:
# the create screen, the View page, the printed GRN and the
# database row.
# ============================================================

import random
import time

import allure
import pytest

from backoffice.dbchecks import grn as grn_db
from backoffice.pages.purchase.purchase_receive_page import PurchaseReceivePage, to_number
from backoffice.support import requires

pytestmark = [pytest.mark.client_issue, pytest.mark.module]

TOLERANCE = 0.005

# The client's own invoice: rates that do not divide cleanly and a VAT
# mix of 17.4 / 17.39 / 15 / 0, because a GRN where every line carries
# the same VAT would not exercise what they reported.
CLIENT_SHAPES = [
    (900, "29.98", "40", "17.4"),
    (120, "38.80", "45", "0"),
    (150, "23.50", "30", "0"),
    (180, "4.05", "5.4", "17.4"),
    (90, "7.55", "10.07", "17.39"),
    (50, "70.00", "80", "0"),
    (30, "59.99", "80", "17.4"),
    (17, "13.33", "18", "17.4"),
    (288, "4.44", "6", "17.39"),
    (240, "25.00", "33", "15"),
    (980, "27.52", "35", "17.4"),
    (200, "81.88", "99", "0"),
    (300, "59.17", "72", "17.4"),
    (384, "120.83", "150", "17.39"),
    (7, "3.33", "5", "15"),
]

# Fractional VAT percentages. Whole numbers divide too kindly - a
# percentage like 17.39 of an odd amount lands between paisa, which is
# where a rounding step has something to lose.
FRACTIONAL_VATS = ["17.39", "15.25", "7.45", "4.87", "2.63", "0"]


def heavy_shapes(count, seed):
    """`count` lines, each one deliberately awkward.

    quantity  over 100, and different on every line
    rate      over 100 taka, never a round number (the field keeps 2
              decimals, so 2 is as fractional as it can be made)
    VAT       a fractional percentage, mixed across the lines

    Seeded, so the report can name the seed and the exact run can be
    repeated.
    """
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        qty = 100 + rng.randint(1, 400)
        rate = rng.uniform(100.01, 1999.99)
        # never let it land on a round figure
        if abs(rate - round(rate)) < 0.01:
            rate += 0.37
        selling = rate * rng.uniform(1.15, 1.6)
        out.append((qty, "%.2f" % rate, "%.2f" % selling, rng.choice(FRACTIONAL_VATS)))
    return out


SCENARIOS = {
    "client invoice": {"lines": 15, "discount": "2.67", "shapes": None},
    "heavy": {"lines": 30, "discount": "3.47", "shapes": "heavy"},
}


def _attach(name, body):
    text = body if isinstance(body, str) else str(body)
    print("\n--- %s ---\n%s" % (name, text))
    allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)


@pytest.mark.parametrize("scenario", list(SCENARIOS), ids=list(SCENARIOS))
@allure.feature("Purchase")
@allure.story("GRN amount must survive being saved")
@allure.severity(allure.severity_level.CRITICAL)
def test_multi_item_grn_keeps_its_amount(page, profile, scenario):
    """A many-line GRN stores exactly the amount it showed."""
    requires(profile, screen="purchase_receive", button=True,
             data=[("office",), ("receive",)])
    setup = SCENARIOS[scenario]
    allure.dynamic.title("%d-line GRN keeps its amount (%s) - %s"
                         % (setup["lines"], scenario, profile.label))

    receive_data = profile.data("receive")
    supplier_id = receive_data.get("supplier_id")
    if not supplier_id:
        pytest.skip("profiles/%s.py has no master['receive']['supplier_id'] - "
                    "needed to pick items this supplier can be received against"
                    % profile.key)

    items = grn_db.receivable_items(supplier_id, setup["lines"])
    if len(items) < 2:
        pytest.skip("only %d receivable item(s) for supplier %s"
                    % (len(items), supplier_id))

    seed = int(time.time())
    if setup["shapes"] == "heavy":
        shapes = heavy_shapes(len(items), seed)
        _attach("how this run was shaped",
                "%d lines, seed %d\nevery quantity over 100, every rate over 100 taka and\n"
                "fractional, fractional VAT, %s%% discount"
                % (len(items), seed, setup["discount"]))
    else:
        shapes = CLIENT_SHAPES
        _attach("how this run was shaped",
                "%d lines using the client's own rates and VAT mix, %s%% discount"
                % (len(items), setup["discount"]))

    _attach("items taken from the database",
            "\n".join("%-16s %s" % (i["ItemCode"], i["ItemName"]) for i in items))

    challan = "QA-%s-%s" % ("HEAVY" if setup["shapes"] else "MULTI",
                            time.strftime("%y%m%d-%H%M%S"))
    receive = PurchaseReceivePage(page, profile)

    with allure.step("Open Direct Receive and fill the header"):
        receive.open_form()
        # VAT on top, the way a supplier invoice states it.
        receive.set_price_including_vat(False)
        receive.fill_header(
            office=profile.data("office"),
            warehouse=receive_data["warehouse"],
            supplier=receive_data["supplier"],
            challan_no=challan,
            payment_method=receive_data.get("payment_method", "Cash"),
            supplier_query=receive_data.get("supplier_query"))

    expected = []
    with allure.step("Add %d lines" % len(items)):
        for n, item in enumerate(items):
            qty, rate, selling, vat = shapes[n % len(shapes)]
            try:
                typed = receive.add_line(item_code=item["ItemCode"],
                                         item_name=item["ItemName"],
                                         quantity=qty, rate=rate,
                                         selling_price=selling, vat_percent=vat)
            except AssertionError as e:
                _attach("line %d could not be added" % (n + 1),
                        "%s (%s)\n%s" % (item["ItemCode"], item["ItemName"], str(e)[:200]))
                continue
            expected.append({
                "code": item["ItemCode"], "name": item["ItemName"],
                "qty": qty, "rate": float(rate), "vat_pct": float(vat),
                "item_total": round(qty * float(rate), 2),
                "vat_amount": round(qty * float(rate) * float(vat) / 100.0, 2),
                "rate_kept": to_number(typed["rate_field"]),
            })

    assert len(expected) >= 2, "fewer than two lines went on - nothing to compare"
    _attach("lines added", "%d of %d" % (len(expected), len(items)))

    changed = [e for e in expected if e["rate_kept"] != e["rate"]]
    if changed:
        _attach("rates the form would not keep",
                "\n".join("%s: typed %.4f, kept %s" % (e["code"], e["rate"], e["rate_kept"])
                          for e in changed))

    with allure.step("Apply the header discount"):
        receive.set_discount_percent(setup["discount"])

    before = receive.totals()
    _attach("totals BEFORE save", before)

    # Worked out here, independently of the screen, so a wrong screen and
    # a wrong save cannot agree with each other and both pass.
    own_item_total = round(sum(e["item_total"] for e in expected), 2)
    own_vat = round(sum(e["vat_amount"] for e in expected), 2)
    own_with_vat = round(own_item_total + own_vat, 2)
    own_discount = round(own_with_vat * float(setup["discount"]) / 100.0, 2)
    _attach("worked out from the lines themselves",
            "item total      %12.2f\nVAT             %12.2f\nwith VAT        %12.2f\n"
            "%s%% discount   %12.2f\nshould be payable %10.2f"
            % (own_item_total, own_vat, own_with_vat, setup["discount"],
               own_discount, round(own_with_vat - own_discount, 2)))

    with allure.step("Save"):
        receive.save_receive()
        toast = receive.toast(timeout_seconds=25)
        _attach("app response", "%s\nurl: %s" % (toast or "(no toast)", page.url))
        assert receive.saved() or "success" in (toast or "").lower(), (
            "the GRN did not save - the app said: %s" % (toast or "nothing"))

    with allure.step("Read the stored GRN"):
        header = grn_db.header_by_challan(challan)
        assert header, "saved, but no GRN row with challan %r" % challan
        lines = grn_db.lines_of(header["PurchaseReceiveId"])
        stored = grn_db.as_totals(header)
        _attach("stored header", "%s\n%s" % (header["PurchaseReceiveCode"], stored))

    # ---- line by line ------------------------------------------------
    rows = [("item", "qty", "rate", "expected", "stored", "diff")]
    bad_lines = []
    by_name = {str(l["ItemName"]): l for l in lines}
    for e in expected:
        line = by_name.get(str(e["name"]))
        if line is None:
            rows.append((str(e["name"])[:22], e["qty"], "%.2f" % e["rate"],
                         "%.2f" % e["item_total"], "MISSING", "-"))
            bad_lines.append((e["name"], e["item_total"], None, None))
            continue
        kept = float(line["TotalAmount"] or 0)
        delta = round(kept - e["item_total"], 4)
        rows.append((str(e["name"])[:22], e["qty"], "%.2f" % e["rate"],
                     "%.2f" % e["item_total"], "%.2f" % kept, "%+.2f" % delta))
        if abs(delta) > TOLERANCE:
            bad_lines.append((e["name"], e["item_total"], kept, delta))
    _attach("EVERY LINE: quantity x rate vs what was stored",
            "\n".join("%-24s %6s %9s %12s %12s %8s" % r for r in rows))

    sum_of_lines = round(sum(float(l["TotalAmount"] or 0) for l in lines), 2)
    header_gap = round(sum_of_lines - float(header["ItemTotalAmount"] or 0), 2)
    _attach("header vs its own lines",
            "sum of line totals     %12.2f\nheader ItemTotalAmount %12.2f\n"
            "difference             %12.2f" % (sum_of_lines,
                                               float(header["ItemTotalAmount"] or 0),
                                               header_gap))

    # ---- the whole GRN, everywhere it is shown ------------------------
    view = receive.open_saved_view(header["PurchaseReceiveCode"])
    _attach("totals on the View page", view)
    printed = {}
    try:
        receive.open_received_list()
        printed_url, printed = receive.open_printed_grn(header["PurchaseReceiveCode"])
        _attach("totals on the printed GRN (%s)" % printed_url, printed)
    except Exception as e:
        _attach("printed GRN could not be opened", str(e)[:300])

    def _pick(source, *names):
        for n in names:
            if source.get(n) is not None:
                return source[n]
        return None

    payable = {
        "create screen": before.get("Purchase Total"),
        "View page": _pick(view, "Total Price", "Purchase Total"),
        "printed GRN": _pick(printed, "Purchase Total", "Total Price"),
        "database": stored.get("Purchase Total"),
    }
    seen = {k: v for k, v in payable.items() if v is not None}
    spread = (max(seen.values()) - min(seen.values())) if len(seen) > 1 else 0.0
    _attach("AMOUNT PAYABLE, everywhere",
            "\n".join("%-16s %s" % (k, "-" if v is None else "%.2f" % v)
                      for k, v in payable.items())
            + "\n\nwidest difference: %.2f  (over %d lines)" % (spread, len(expected))
            + "\n\nchallan %s, GRN %s" % (challan, header["PurchaseReceiveCode"]))

    # The discount is where the fifteen-line run lost its two paisa, so
    # show that sum explicitly rather than leaving it to be inferred.
    stored_disc = stored.get("Discount")
    stored_item = stored.get("Item Total")
    stored_vat = stored.get("Total VAT")
    if None not in (stored_disc, stored_item, stored_vat):
        consistent = round(stored_item + stored_vat - stored_disc, 2)
        _attach("does the saved header add up on its own terms?",
                "item total %12.2f\n+ VAT      %12.2f\n- discount %12.2f\n= %14.2f\n"
                "stored payable %10.2f   difference %+.2f"
                % (stored_item, stored_vat, stored_disc, consistent,
                   stored.get("Purchase Total", 0),
                   round(stored.get("Purchase Total", 0) - consistent, 2)))

    # ---- verdict -------------------------------------------------------
    problems = []
    if bad_lines:
        problems.append("%d of %d lines do not equal quantity x rate"
                        % (len(bad_lines), len(expected)))
    if abs(header_gap) > TOLERANCE:
        problems.append("the header is %+.2f away from the sum of its lines" % header_gap)
    if spread > TOLERANCE:
        problems.append("the payable amount differs by %.2f between screens" % spread)

    assert not problems, (
        "a %d-line GRN did not keep its amount:\n  " % len(expected)
        + "\n  ".join(problems)
        + "\n\nchallan %s, GRN %s - see the attached line-by-line table"
        % (challan, header["PurchaseReceiveCode"]))
