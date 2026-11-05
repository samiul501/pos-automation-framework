# Session-close reproduction

One command reproduces the POS session-close defect from a clean slate:

```
python reproduce_session_close_bug.py
```

Takes about 7 minutes and ends with a verdict.

This lives outside `positive_tests/` and `negative_tests/` on purpose — it is a
standalone reproduction, not part of the regression suite.

## The defect

After a logout, pressing **Session Close** writes `ClosingDatetime` into the
exe's own database and sets `IsSync = 1` without the server ever accepting the
close. The cashier is shown success, nothing is queued for retry, nothing is
written to `AppLog`, and the session stays open on the server permanently.

Open and close inside one login and the close reaches the server correctly.
Log out once in between and it is lost, silently. The logout is the trigger.

## What the run does

| Step | Action |
|---|---|
| 1 | Resets the installed MSIX package, clearing `LocalState` |
| 2 | Signs in to devdemostore, POS → Setup → Counter Setup → `sami2` → Generate Token → **Generate New**, and reads the new token back |
| 3 | Registers the exe with it: first five checkboxes on the left, first three in the middle, Item Code Length `4`, Save |
| 4 | Logs in as `<user-id> / <password>` |
| 5 | Outlet → `sami2` → Open Session → Let's Start, and confirms the session landed on the server |
| 6 | One sale — customer `01700000006`, barcode `4040`, 732.00 |
| 7 | **Logs out without closing** — the trigger |
| 8 | Same employee logs back in → Lock Session → Session Close → authorise → Close Session |
| 9 | Compares `pos.CounterSession` against the exe's own SQLite and prints the verdict |

Screenshots of each step land in `shots/`.

## Verdict, and the exit code

| Printed | Exit | Meaning |
|---|---|---|
| `BUG REPRODUCED` | 1 | exe closed it, server did not — the defect |
| `NOT REPRODUCED` | 0 | the close reached the server — fixed |
| `INCONCLUSIVE` | 2 | the two disagree some other way; read the output |

Once the fix ships, a `NOT REPRODUCED` with exit 0 is the confirmation.

## Options

```
python reproduce_session_close_bug.py --skip-setup
```

Reuses the current registration instead of resetting — faster, but only valid
if the exe is already registered against `sami2`.

## Requirements

- `playwright` (plus `python -m playwright install chromium`), `pywinauto`, `pywin32`, `pyodbc`
- `../.env` with the devdemostore credentials and the SQL Server connection
- The POSAPP MSIX package installed, and `sami2` active in the back office

## Settings

At the top of the script: `COUNTER_ID` / `COUNTER_NAME`, `EMPLOYEE` / `PASSWORD`,
`CUSTOMER`, `BARCODE`, and the checkbox lists used on the Registration screen.

`BARCODE` must be stocked in the counter's warehouse (16) — an item with company-wide
stock but none in that warehouse is refused with **"Out Of Stock !"**. `4040`
(Boal Fish 1 Medium, 732.00) was verified against `pos.POSSalesDeliveryLine`.

## Notes for anyone extending this

Things that cost time to work out, confirmed live on build 5.0.58.0:

- Popups respond only to their own **OK** button — `Enter` does nothing.
- **Session Close** is reached through **Lock Session (Alt + L)**, not through the
  Outlet screen, which keeps showing "Open Session" even while a session is open.
- The authorise overlay appears **after** pressing Session Close, not before.
- `Alt+L` is unreliable; click the on-screen button instead.
- The token box exposes no `ValuePattern`, and the token is 2112 characters — it
  has to be pasted via the clipboard.
- The selected counter shows as the `cmbo_market_ID` label inside the combo, not
  as the combo's `window_text()`.
- "Let's Start" carries a typographic apostrophe, so match it by `auto_id`
  (`PrimaryButton`), not by title.
- Searching for a button titled `Close` matches the window chrome too, so it is
  ambiguous — use the specific title or `auto_id`.

## Related

Full write-up with evidence and screenshots:
`../backoffice/bug-reports/pos-session-close-not-saved/`
