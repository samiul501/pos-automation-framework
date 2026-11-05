# ============================================================
# NEGATIVE TEST DATA - invalid input combinations, one list per
# step. Only edit this file to add/change negative cases.
# ============================================================

import config

# ---- Login: invalid credential combinations ----
LOGIN_NEGATIVE_CASES = [
    {
        "case_id": "wrong_password",
        "user_id": config.USER_ID,
        "password": "wrongpass999",
        "description": "Valid User ID + wrong Password",
    },
    {
        "case_id": "wrong_user_id",
        "user_id": "999999",
        "password": config.PASSWORD,
        "description": "Wrong User ID + valid Password",
    },
    {
        "case_id": "both_wrong",
        "user_id": "999999",
        "password": "wrongpass999",
        "description": "Wrong User ID + wrong Password",
    },
    {
        "case_id": "blank_user_id",
        "user_id": "",
        "password": config.PASSWORD,
        "description": "Blank User ID + valid Password",
    },
    {
        "case_id": "blank_password",
        "user_id": config.USER_ID,
        "password": "",
        "description": "Valid User ID + blank Password",
    },
    {
        "case_id": "both_blank",
        "user_id": "",
        "password": "",
        "description": "Blank User ID + blank Password",
    },
]

# ---- Transaction: invalid item barcode ----
TRANSACTION_ITEM_NEGATIVE_CASES = [
    {
        "case_id": "invalid_item_barcode",
        "customer": config.TRANSACTIONS[0]["customer"],
        "item_barcode": "88888888888",
        "description": "Non-existent item barcode should not be added to the cart",
    },
]

# ---- Transaction: invalid customer should block the sale ----
TRANSACTION_CUSTOMER_NEGATIVE_CASES = [
    {
        "case_id": "invalid_customer",
        "customer": "999999999",
        "item_barcode": config.TRANSACTIONS[0]["items"][0],
        "valid_customer": config.TRANSACTIONS[0]["customer"],
        "description": "Invalid/non-existent customer should not allow completing a sale",
    },
]

# ---- Transaction: sale without a customer should be blocked ----
# Verified live: adding an item with no customer is allowed, but trying to
# confirm payment shows a "Customer Information Not Found" popup
# (Ok = auto_id "PrimaryButton"); dismissing it with Enter leaves the sale
# blocked (item still in the cart) until a valid customer is entered.
TRANSACTION_BLANK_CUSTOMER_NEGATIVE_CASES = [
    {
        "case_id": "blank_customer",
        "items": ["4040", "4041"],
        "valid_customer": "01700000011",
        "description": "Completing a sale with no customer should be blocked until a valid customer is entered",
    },
]

# ---- Transaction: underpay should be rejected, exact amount should then succeed ----
TRANSACTION_UNDERPAY_NEGATIVE_CASES = [
    {
        "case_id": "underpay_then_correct",
        "customer": config.TRANSACTIONS[0]["customer"],
        "items": config.TRANSACTIONS[0]["items"],
        "description": "Paying less than the Sale Amount should be rejected; retrying with the exact amount should then succeed",
    },
]

# ---- Transaction: customer-group discount must not leak to other customers ----
# "chips Berry" (A0104000003) has an active "VIP_partners" group discount
# (200 -> 190, 5%, valid 2026-08-13 to 2027-06-16 - see the admin panel's
# Discount & Offer setup, customer 01700000010/"Alex"). "01700000007" is NOT
# in that group - verified live: full price 200.00, TextBoxTotalDiscount 0.00.
DISCOUNT_GROUP_CUSTOMER = "01700000010"
DISCOUNT_ITEM_A = "A0104000003"   # chips Berry: 200 -> 190
DISCOUNT_ITEM_B = "FG-01080"      # Meridian Mustard Sauce 250g: 150 -> 142.50
OTHER_GROUP_CUSTOMER = "01700000007"

# ---- Discount: valid group customer + 2 valid products -> discount applies ----
# Verified live: customer 01700000010 + items A0104000003 (200->190) and
# FG-01080 (150->142.50) together -> TotalBill 350.00, TotalDiscount 17.50
# (5% of 350), GrandTotal 333.
DISCOUNT_VALID_CASE = {
    "customer": DISCOUNT_GROUP_CUSTOMER,
    "items": [DISCOUNT_ITEM_A, DISCOUNT_ITEM_B],
    "expected_total_bill": "350.00",
    "expected_total_discount": "17.50",
    "expected_grand_total": "333",
    "description": "Valid group customer + 2 discounted products should show the correct discounted price",
}

TRANSACTION_DISCOUNT_NEGATIVE_CASES = [
    {
        "case_id": "discount_not_applied_other_customer",
        "customer": OTHER_GROUP_CUSTOMER,
        "item_barcode": DISCOUNT_ITEM_A,
        "expected_full_price": "200",
        "description": "Customer outside the discounted group should be charged the full price, not the group-discounted price",
    },
]

# ---- Discount: no customer entered -> discount should not show ----
# Uses ITEM_B and a customer distinct from the other discount cases
# (rather than repeating ITEM_A/OTHER_GROUP_CUSTOMER back-to-back) so this
# case's sale doesn't collide with the app's own "please wait 30 seconds
# before repeating this action" duplicate-sale guard, which fires on an
# identical customer/item/amount combo run too soon after another.
DISCOUNT_BLANK_CUSTOMER_CASE = {
    "item_barcode": DISCOUNT_ITEM_B,
    "expected_full_price": "150",
    "cleanup_customer": config.TRANSACTIONS[0]["customer"],
    "description": "Discount should not be shown/applied when no customer is entered",
}

# ---- Discount: switching customer mid-cart should recalculate the discount ----
# Known defect, verified live 2026-08-13: adding the item as a non-group
# customer (full price 200/0.00), then switching to the discounted-group
# customer, does NOT recalculate - GrandTotal/TextBoxTotalDiscount stay
# stale at 200/0.00 instead of updating to 190/10.00. This case is expected
# to FAIL until the app recalculates discounts on customer change.
DISCOUNT_CUSTOMER_SWITCH_CASE = {
    "item_barcode": DISCOUNT_ITEM_A,
    "initial_customer": OTHER_GROUP_CUSTOMER,
    "switch_to_customer": DISCOUNT_GROUP_CUSTOMER,
    "expected_discounted_total": "190",
    "expected_total_discount": "10.00",
    "description": "Switching to the discounted-group customer mid-cart should recalculate and apply the discount",
}

# ---- Discount: should scale proportionally with quantity ----
# Verified live: scanning the same barcode twice sets Qty=2.0, and
# TotalBill/TotalDiscount/GrandTotal scale to 400.00/20.00/380 (5% of 400),
# not a flat per-transaction amount.
DISCOUNT_QUANTITY_SCALING_CASE = {
    "customer": DISCOUNT_GROUP_CUSTOMER,
    "item_barcode": DISCOUNT_ITEM_A,
    "quantity": 2,
    "expected_total_bill": "400.00",
    "expected_total_discount": "20.00",
    "expected_grand_total": "380",
    "description": "The group discount should scale proportionally with quantity",
}

# ---- Discount: should stack correctly with a manual Cost Guard (F4) offer ----
# Verified live: group discount (200 -> 190) applied first, then a manual
# 10% Percentage offer compounds on the already-discounted amount
# (10% of 190 = 19.00), landing on GrandTotal 171 - not a conflict, not a
# double-count of the same base amount.
DISCOUNT_MANUAL_OFFER_COMBO_CASE = {
    "customer": DISCOUNT_GROUP_CUSTOMER,
    "item_barcode": DISCOUNT_ITEM_A,
    "offer_discount_type": "Percentage",
    "offer_discount_value": "10",
    "expected_total_discount": "10.00",
    "expected_other_discount": "19.00",
    "expected_grand_total": "171",
    "description": "The manual Cost Guard offer should stack (compound) on top of the group discount, not conflict or double-count",
}

# ---- Discount: should survive a Hold -> Recall cycle ----
# Verified live 2026-08-14: the discount amount (200 -> 190) survives Hold
# and Recall correctly, but TextBoxTotalDiscount's FORMAT changes from
# "10.00" to "10" after a recall (numerically identical - a minor cosmetic
# formatting quirk, not a business-logic defect).
DISCOUNT_HOLD_RECALL_CASE = {
    "customer": DISCOUNT_GROUP_CUSTOMER,
    "item_barcode": DISCOUNT_ITEM_A,
    "expected_grand_total": "190",
    "expected_total_discount_after_recall": "10.00",
    "description": "Discount should still apply correctly after a Hold -> Recall cycle",
}

# ---- Discount: after Hold -> Recall, switching customer away then back ----
# Verified live 2026-08-14: after Hold->Recall (discount 190 intact),
# switching to a non-group customer correctly REMOVES the discount
# (200/0.00) - recalculation works in this direction. But switching BACK
# to the group customer does NOT re-apply it (stays 200/0.00 instead of
# 190/10.00) - recalculation only works for removal, not addition. A more
# precise variant of the general customer-switch defect, in the specific
# Hold->Recall context. Expected to FAIL until the app recalculates
# discounts correctly in both directions.
DISCOUNT_HOLD_RECALL_SWITCH_CASE = {
    "group_customer": DISCOUNT_GROUP_CUSTOMER,
    "other_customer": OTHER_GROUP_CUSTOMER,
    "item_barcode": DISCOUNT_ITEM_A,
    "expected_grand_total_discounted": "190",
    "expected_total_discount_discounted": "10.00",
    "expected_grand_total_full_price": "200",
    "description": "After Hold -> Recall, switching away then back to the group customer should re-apply the discount",
}

# ---- Hold & Recall: an already-completed invoice should not be recallable twice ----
# Verified live 2026-08-14: Hold -> Recall -> Payment, then a second Recall
# attempt right after correctly comes back empty (rows=0, TextBoxTotalBill
# "0.00") - the app does NOT let you recall/re-sell an already-completed
# invoice. No bug found here, but kept as a regression guard.
DOUBLE_RECALL_CASE = {
    "customer": OTHER_GROUP_CUSTOMER,
    "item_barcode": "4040",
    "description": "An already-completed invoice should not be recallable a second time (avoid duplicate sale)",
}

# ---- Hold & Recall: recalling a SPECIFIC (non-latest) invoice among multiple holds ----
# Verified live 2026-08-14: clicking the target row's body (NOT the
# btnRecallInvoiceView button, which just discards the row without loading
# it) then pressing Enter correctly restores that specific invoice's
# customer/item - not the latest one's. The TARGET here is the
# discounted-group customer's invoice (group discount + manual Cost Guard
# offer stacked), held in the MIDDLE of three - a plain distractor is held
# before it (oldest) and another plain distractor after it (latest), so
# recalling the target proves a specific non-latest row is selected, not
# just "whatever was held first".
RECALL_SPECIFIC_INVOICE_CASE = {
    "before_customer": "01700000007",
    "before_item": "4040",
    "target_customer": DISCOUNT_GROUP_CUSTOMER,
    "target_item": DISCOUNT_ITEM_A,
    "target_offer_discount_type": "Percentage",
    "target_offer_discount_value": "10",
    "after_customer": "01700000006",
    "after_item": "4041",
    "description": "Recalling the discounted-group customer's invoice, held in the middle of three, should restore that invoice's own customer/item/discount - not the latest one's",
}

# ---- Return: quantity validation (over-return block, partial return,
# remaining-quantity tracking, full-return removal) ----
# Verified live 2026-09-07/09-09: sells 4 distinct items, 2 of them at
# quantity 2 each (4040, 4041) and 2 at quantity 1 each (4042, 3030), then
# in Return:
#  - for 4040 (qty 2), the Return popup's "Exc.Qty" cell (double-click to
#    edit) rejects an over-return attempt (typing "3") and reverts to the
#    max valid quantity (2) - confirmed by then re-editing to a valid "1"
#    (partial return), which IS accepted.
#  - that partial return (1 of 2) is added to the cart, where the main
#    ItemGrid's own Quantity cell is ALSO independently editable
#    (double-click) and ALSO rejects an over-return attempt (typing "-2"
#    reverts back to "-1").
#  - for 4042 (qty 1), a full return is added to the cart; attempting to
#    edit its quantity down to "0" in the main cart is rejected and
#    reverts to the original "-1.00" (you cannot zero-out/cancel a return
#    line this way).
#  - after paying, reopening Return on the SAME invoice shows 4040 with
#    exactly 1.0000 remaining (2 purchased - 1 returned), 4042 GONE
#    entirely (fully returned = no longer returnable = the real
#    double-return protection, not an invoice-level block), and
#    3030/4041 unchanged at their original quantities.
RETURN_QUANTITY_VALIDATION_CASE = {
    "customer": "01700000005",
    # 4040 x2, 4041 x2, 4042 x1, 3030 x1 - scanned as a flat barcode list,
    # duplicates increment quantity on the existing line.
    "items": ["4040", "4040", "4041", "4041", "4042", "3030"],
    "partial_return_item": "4040",
    "partial_return_purchased_qty": "2",
    "over_return_attempt": "3",
    "partial_return_qty": "1",
    "cart_over_return_attempt": "-2",
    "full_return_item": "4042",
    "zero_qty_attempt": "0",
    "unchanged_items": ["3030", "4041"],
    "description": "Return must block over-return and zero-quantity edits (both in the Return popup and the main cart), support a genuine partial return, and correctly track/remove remaining returnable quantity on re-search",
}
