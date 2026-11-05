# DemoStore DB — the five POS domains

Scope note: this database has ~222 tables whose names look POS-related, but most
belong to production, HR, ecom and RTM modules the POS exe never touches. Only the
five domains below matter for these test suites. Everything here was confirmed by
querying the live server, not read off a diagram.

Connection: `db.example.local` / `DemoStore`, credentials in `.env` (gitignored).
Access is READ-ONLY — `db_helpers._query` refuses any statement that is not
SELECT/WITH and the connection is opened `readonly=True`. Test data is created
through the POS UI, the way a cashier would, never by INSERT.

---

## 1. Customer — `dbo.Partner`

44,270 rows, 100 columns. **Not a customer-only table.**

| PartnerTypeId | Name | Rows |
|---|---|---|
| 1 | Customer | 41,798 |
| 2 | Supplier | 2,078 |
| 6 | Loan Employee | 392 |
| 3 / 4 | Loan Partner / Supplier & Customer | 1 each |

Every customer lookup must filter `PartnerTypeId = 1`, or a supplier's mobile number
comes back as a "customer" and the POS rejects it at the till for a reason the test
cannot see. `db_helpers.find_customers()` already does this.

Duplicate mobile numbers are real (`01700000010` is both "Alex" and "mahin"). Which
row the POS picks decides whether a group discount applies — use
`find_active_customer_numbers()`, which returns only unambiguous numbers.

Point-related columns live on this table: `Points`, `PointsAmount`, `PointPerValue`,
`PointOfferId`, `LastRedeemPoint`, `PointExpiryDays`, `MembershipExpiryDays`.

Groups: `dbo.PartnerGroupType` (43 rows). 41,548 of 41,798 customers are in
`PartnerGroupId = 0` ("Test"), so a group-discount test needs a deliberately grouped
customer — e.g. `Lifecare Gold Customer` (35), `Pos Group` (5), `Amit_partners` (1).

## 2. Employee / login — `dbo.Employee` + `dbo.User`

`dbo.Employee` (473 rows) is HR master data. `dbo.User` is what the POS exe actually
authenticates against, joined on `EmployeeId`. Passwords are stored in plain text.

**`POS_USER_ID=100001` is `User.EmployeeLoginId` / `Employee.EnrollNumber` — not an
EmployeeId.** The `.env` account resolves to:

    User 312 "Samiul"  ->  Employee 413, QA, Demo Super Shop
    RoleName "Super Admin", isMasterUser = 1

Permission flags on `dbo.User` gate POS features. Check these first when a UI step is
*missing* rather than broken — the app hides what the user may not do:

`IsPosAdmin`, `IsSpecialDiscount`, `isReturn`, `IsExchange`, `isRePrint`,
`isInvoiceEdit`, `isRecallAuthorization`, `isHoldAuthorization`, `IsBackDate`,
`IsBlock`, `LoginFailedCount`.

`Employee.isUser = 1` marks who can log in at all (293 active, 14 inactive).

## 3. Product — `dbo.Item`

44,643 rows, 144 columns. Categories in `dbo.ItemCategory` (465 rows).

Branches, because the same barcode legitimately exists per branch:

| Branch | Items |
|---|---|
| Mirpur-13 | 31,419 |
| DemoStore BD | 5,717 |
| Demo Retail Ltd | 2,858 |
| Demo Super Shop | 2,234 |
| DEMO_STORE | 2,214 |

**`IsSaleAble` is a trap — do not filter on it.** 38,658 active items have
`IsSaleAble = 0` and sell perfectly well: "Beef Bone Full" (barcode 3030) has 8,686
sold lines with the flag off. The real gate is `IsActive = 1` plus a proven sales
history, which is what `find_sellable_items()` checks.

## 4. Special discount — `pos.POSSpecialDiscount`

25 rows. Note: `dbo.SpecialDiscountHeader` is **empty (0 rows)** — wrong table.

`DiscountType` decodes as:

| Value | Meaning |
|---|---|
| 0 | Open / Cost-Guard (header `Value` is 0, cashier types the amount) |
| 1 | Fixed amount |
| 2 | Percentage |

Supporting tables:

- `pos.POSSpecialDiscountCustomerInfo` — who it applies to. `IntType` 1 = CustomerGroup,
  2 = Customer. `StrTypeName = 'All'` with `IntCustomerGroupId = 0` means everyone.
- `pos.POSSpecialDiscountItemExcluding` — items the offer must skip.
- `pos.PosspecialDiscountApproval` — which user may authorise which value band.

Header columns that change runtime behaviour: `IsAutoApplied`, `IsCapped` /
`CappedAmount`, `DailyLimit`, `IsRequiredComment`, `IsItemWiseOpenDiscount`,
`MinAmount` / `MaxAmount`, `CounterIds`, `CustomerGroupIDs`.

`pos_actions.do_offer_flow()` selects the list entry literally named "Open"
(`IsOpenDiscount = 1`). `db_helpers.get_active_open_discounts()` is the pre-check —
if it returns nothing, the offer test is un-runnable and should skip, not fail.

## 5. Redeem point — a four-part chain

    promo.tblPointOffer          (earn rule: how many points per taka)
      -> dbo.Partner.Points      (balance, linked by Partner.PointOfferId)
      -> pos.tblPointRedemption* (voucher / redeem transaction)
      -> pos.CustomerPointExpiryHistory (expiry)

- **`promo.tblPointOffer`** (75 rows) + `tblPointOfferRow` (item scope, 55).
  `intOrderValueFrom`/`To` → `intOfferPoint`; `intOfferPointInTaka` is the cash value
  of one point. `CalculationTypeName` is "Actual" or "Rounding". `PointRedemptionCap`
  caps a single redeem — some rows hold junk values (`-100`, `0`).
- **`dbo.Partner.PointOfferId`** links a customer to their earn rule. 41,148 customers
  point at offer 2 ("Membership-1 x 2"). **272 customers have `PointOfferId = 0`, which
  matches no offer** — they earn nothing, and that is a data bug, not an app bug.
- **`pos.tblPointRedemptionHeader`** (120) — `PointRedemptionType` 1 = "Voucher
  Generate" (95), 2 = "Clear Balance" (20). Rows in **`pos.tblPointRedemptionRow`**
  (28,499) carry `RedeemCode`, `GainedPoint`, `RedeemPoint`, `RemainingPoint`,
  `IsUsed`, `ExpiryDate`.
- **`pos.CustomerPointExpiryHistory`** (3,987) — per-invoice point expiry.

The sale itself records the outcome, so a point test can assert straight off the
invoice header. `pos.POSSalesDeliveryHeader` carries: `Points`, `PointRedeemCode`,
`RedeemPoint`, `RedeemPointValue`, `PointOfferId`, `PointExpiryDays`, `PointExpiryDate`.

`promo.tblRewardPointHeader` / `tblRewardPointRow` / `promo.tblLoyaltyReward*` are all
**empty** — they are not the live path, despite the promising names.

---

## Rules that break naive lookups

1. **Barcode OR ItemCode.** The POS item search box resolves a typed value against
   both columns. "4040" matches `Barcode`; "3031" matches `ItemCode`. A lookup that
   checks only `Barcode` wrongly reports half the test data as missing.
2. **`IsActive = 0` is a silent no-op.** The app adds nothing to the cart and shows no
   error popup (barcode `A0104000001`, Salt-1). This was once misdiagnosed as a lapsed
   discount.
3. **Expired offer tables mislead.** `pos.OfferSetupHeader`, `promo.tblPromotionHeader`
   and `pos.posItemVatDiscountHeader` are fully expired and are not where the live
   customer-group discount comes from. The trustworthy signal is the last real sale —
   `db_helpers.get_last_group_discount_for_item()`.
