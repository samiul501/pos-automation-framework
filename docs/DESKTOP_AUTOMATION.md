# Automating the POSAPP desktop application

How the exe side of this framework was built, and why each piece is the way it
is. Most of what follows was learned by losing a run to it first — the
reasoning is kept so the next person does not pay for the same lesson twice.

---

## 1. What we are driving

POSAPP POS is a **WinUI 3 desktop application packaged as MSIX**. That
single sentence decides almost everything below.

| Consequence | Why it matters |
|---|---|
| No `.exe` path to launch | MSIX apps are activated by identity, not by file path |
| Identity changes on every rebuild | The publisher hash in the package family name moves |
| All data lives in a sandbox | `%LOCALAPPDATA%\Packages\<family>\LocalState` |
| It can be reset to factory state | `Reset-AppxPackage` — the cleanest possible starting point |
| UI is exposed through **UI Automation** | So `pywinauto`'s `uia` backend, not `win32` |

The framework talks to it with **pywinauto (UIA backend)** and nothing else —
no image matching, no fixed coordinates, no OCR. Every control is addressed by
its `auto_id`, which survives window moves, DPI changes and theme switches.

---

## 2. Launching it

### Finding the app

There is no path to run. An MSIX app is launched through its **AUMID**
(Application User Model ID):

```
explorer.exe shell:AppsFolder\CF9BD7D4-...-05D032861D46_6g9azff0e1qkt!App
```

That id is **not hard-coded**. It is resolved at launch time:

```python
powershell -NoProfile -Command "(Get-StartApps -Name '*POSAPP*' | Select-Object -First 1).AppID"
```

**Why:** reinstalling or updating the app changes the publisher hash inside the
package family name even though the app's display name never changes. A
hard-coded id goes stale after every build and the whole suite fails at step
one. `config.APP_ID` remains only as a fallback if the lookup ever fails.

### Waiting for the window

`launch_app()` does not fire-and-sleep. Measured on the test machine a cold
start takes about **17 seconds** to put a window on screen — 3.7s just to
resolve the AppID, 7.5s before the process even exists. The original code slept
a flat 5 seconds and then gave the caller 20 seconds to find a window that was
not there yet; a busy machine failed the whole suite.

So it **polls** for the window, and if nothing has appeared after 45 seconds it
fires the activation once more — a `shell:AppsFolder` activation is
occasionally swallowed outright, and a second attempt costs seconds where a
failed run costs everything.

### Getting a usable window

`get_main_window()` does three things beyond finding the handle:

1. **Tolerates a half-started process.** The UIA tree throws while the app is
   still building its window. That is "not yet", not "no window" — keep polling.
2. **Restores a minimised window.** A minimised window's rectangle collapses to
   `(0,0,0,0)` and any popup inside renders at large negative coordinates. This
   was the root cause of several "button never became visible" timeouts.
3. **Focuses it**, so keyboard input lands where it is meant to.

---

## 3. Addressing controls

Everything is found by `auto_id`. The map below was read off the live
application, not guessed, and is the backbone of every suite.

### Login and registration

| Control | `auto_id` |
|---|---|
| User ID / Password | `userName` / `UserPassword` |
| Login / Registration | `btnLogin` / `btnRegistration` |
| Token box | `txtToken` |
| Item Code Length | `txtItemCodeLength` |
| Go offline | `IsOffline` |

Registration checkboxes, by column — left, middle, right:

```
IsAllowSalesPerson   IsDirectPoint         IsQuantityRescan
IsSync               IsItemSearch          QTYPopupAfterSearch
IsPrint              [Item Code Length]    IsSalesPersonOrService
isDeclarationSlipPrint  ViewItemDetail     IsWithoutRefRetExc
IsHoldInvoicePrint   ViewCostPrice         IsHideStock
IsShowPointOffer     ViewItemCode          IsVATHide
```

Note `isDeclarationSlipPrint` — lower-case first letter, unlike every other id
in the column. Copying the pattern instead of reading the tree fails here.

### The POS screen

| Control | `auto_id` |
|---|---|
| Customer | `txtCustomer`, `btnCustomerSearch`, `CustomerAdd` |
| Item search | `asbItemSearch` → child `TextBox` |
| Cash / totals | `textBoxCashAmount`, `GrandTotal`, `TextBoxTotalDiscount`, `TextBoxTotalBill` |
| Actions | `btnHoldInVoice`, `btnRecallInvoice`, `btnExchange`, `btnReturn` |
| Print / SMS | `btnPrintNew`, `btnPrintSMS` |
| Navigation | `Shell_Main`, `Shell_InvoicePage`, `Shell_Outlet`, `btnLogOut`, `btnOnline` |

### Sessions

| Screen | Controls |
|---|---|
| Outlet | `cmbCusto` (counter), the chosen one shows as the label `cmbo_market_ID` |
| Session Opening | `InputBox` (opening cash), `OpeningNote`, `numBDT1`…`numBDT1000`, `PrimaryButton` = *Let's Start* |
| Lock Session | `PrimaryButton` = Logout, `SecondaryButton` = **Session Close**, `CloseButton` = Cancel |
| Session Closing | `InputBox`, `ClosingNote`, `PrimaryButton` = Pick up, `SecondaryButton` = **Close Session** |

---

## 4. The traps

Each of these cost at least one failed run.

### Popups answer only to their own button

`{ENTER}` does nothing on most dialogs here. "No item selected", "Out Of
Stock!", "Successfully Created" — all of them need their **OK** clicked.
`click_first(win, ("OK", "Ok", "Yes", "No", "Cancel"))` exists for exactly this.

### `Close` is ambiguous

Searching for a button titled `Close` matches the window chrome's close button
*and* the dialog's — pywinauto raises `ElementAmbiguousError`. Use the specific
title or the `auto_id`.

### `Let's Start` carries a typographic apostrophe

`Let’s Start`, not `Let's Start`. Match it by `auto_id` (`PrimaryButton`),
never by title.

### The token box has no ValuePattern

`set_edit_text()` raises `NoPatternInterfaceError`, and the token is **2000+
characters** — far too many to type. It has to go through the clipboard:

```python
to_clipboard(token); send_keys("^a"); send_keys("^v")
```

### The authorise overlay appears *after* Session Close

Not before. A script that looks for the login box first finds nothing, presses
on, and then fails on a closing screen that never opened.

### `Alt+L` is unreliable

The accelerator only fires when focus is not in a text box. Click the on-screen
**Lock Session (Alt + L)** text instead.

### The selected counter is not the combo's text

`cmbCusto.window_text()` is empty even when a counter is chosen. The selection
shows as a child label with `auto_id = cmbo_market_ID`.

### A session service has no desktop

If the CI runner is installed as a **Windows service** it runs in session 0,
which has no desktop at all — every suite fails with "window not found".
It must run as a **startup task for the logged-in user**.

### Stock is per warehouse

An item with 693,458 units company-wide is still **"Out Of Stock !"** if the
counter's warehouse holds none. Pick items from
`pos.POSSalesDeliveryLine WHERE WarehouseId = <the counter's>` — things that
have already rung up there.

---

## 5. Pressing things that resist

`press_button_robust()` tries four methods in order, because no single one
works everywhere:

1. **`invoke()`** — the UIA Invoke pattern. No coordinates, immune to the
   window being partly off-screen. Tried first for that reason.
2. **`click_input()`** — a real mouse click, for controls with no Invoke.
3. **focus + `{ENTER}`**
4. **focus + `{SPACE}`**

For buttons whose shape changes between builds, `wait_and_click_first_available()`
clicks whichever of several `auto_id`s appears first — a Hold confirmation
changed from a Yes/No print question to a single OK button between releases,
and hard-coding either one would break on the other.

### Virtualised grids

Exchange and Return grids recycle their rows. A row reference captured a moment
ago may point at a different record by the time it is clicked.
`select_and_click_latest_row()` therefore re-reads the grid on every attempt,
waits for the row count to stop changing (`wait_for_stable_row_count`), and
clicks at a coordinate **relative to the row's own rectangle** rather than an
absolute position.

---

## 6. Reading the app's own books

The application keeps SQLite databases inside its sandbox:

```
%LOCALAPPDATA%\Packages\<family>\LocalState\
    Database\POS.1.01.db              items, customers, settings, sessions
    Database\POS_Transaction.1.01.db  transactions
    AppLog\AppLog.1.0.db              the application log
```

These are **copied before reading** — never opened in place, never written to.
They are what proves a defect: the session-close bug was found because the
app's own row said closed while the server's said open, and the two were
otherwise identical.

`TblSettings` holds where the exe is pointed (`AppUrl`, `intAccountId`,
`intCounterId`, `StrCounterName`), which is how a registration is verified
rather than assumed. Some settings exist **only** here with no server source —
`IsCustomerGroupInProductDiscount` is one, and a reinstall silently resets it,
which will fail every group-discount test until it is set again.

---

## 7. A clean starting point

```powershell
Get-Process -Name "*POSAPP*" | Stop-Process -Force
Reset-AppxPackage -Package (Get-AppxPackage -Name "<name>").PackageFullName
```

`Reset-AppxPackage` returns the app to factory state — `LocalState` is emptied,
registration is gone. Everything after that is reproducible, which is why the
session-close defect could be pinned to a single variable.

`exe_setup/` turns the sequence that follows into one click: reset → fetch a
fresh token from the back office → register → log in → open a session. It can
take its token from **devdemostore** or **StoreC**.

> The **Generate New** button in the back office must be pressed. Simply
> opening the token popup shows the *existing* token and creates nothing.

---

## 8. Tests that are worth trusting

Two rules keep the suites honest.

**Nothing the application says is evidence.** The screen is a claim to be
checked against `pos.POSSalesDeliveryLine`, `pos.CounterSession` and the printed
invoice. The session-close bug is the case in point: the app reported success,
and only the database disagreed.

**The self check runs before every suite.** It imports every module, scans for
unreachable code, verifies call contracts, `.env` keys and dashboard routes.
It exists because a one-line edit once left `return main_win` stranded after a
`break` — the file compiled, nothing caught it, and it surfaced minutes later
as "POSAPP window not found" on a window that was right there.

---

## 9. Where to start reading

| File | What it holds |
|---|---|
| `pos_helpers.py` | Launching, finding windows, clicking, grids — all app-agnostic |
| `pos_actions.py` | Business actions: login, sell, hold & recall, exchange, return, logout |
| `config.py` | Test data and settings; credentials come from `.env` |
| `exe_setup/setup_tasks.py` | Reset, token, registration, login, session — the whole runway |
| `tools/selfcheck.py` | What runs before every suite, and why |
