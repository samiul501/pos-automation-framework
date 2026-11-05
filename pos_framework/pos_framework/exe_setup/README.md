# exe setup

The chores that come before any testing, one click each. They sit at the top
of the dashboard, above the suites.

| Button | What it does | Takes |
|---|---|---|
| **Reset + Register + Session** | Resets the app, fetches a fresh token from the back office, registers, logs in, opens a session | ~4 min |
| **Register + Session** | The same without the reset — for an app that is already installed and clean | ~4 min |
| **Reset Only** | Resets the installed app and stops, leaving it clean for a manual run | ~15 sec |

From the command line:

```bash
../venv/Scripts/python -u exe_setup/setup_tasks.py full
../venv/Scripts/python -u exe_setup/setup_tasks.py register
../venv/Scripts/python -u exe_setup/setup_tasks.py reset
```

## Which back office

The folder header carries a picker: **devdemostore** or **StoreC**. Whichever
is chosen is where the token is taken from, and the choice is remembered. From
the command line it is `--env`:

```bash
../venv/Scripts/python -u exe_setup/setup_tasks.py full --env storec
```

| | devdemostore | StoreC |
|---|---|---|
| URL | demo-backoffice.example.com | storec-backoffice.example.com |
| Counter | sami2 (CounterId 20183, code 1169) | sami2 (CounterId 387, code 1123) |
| Sign-in | `WEB_MOBILE` / `WEB_PASSWORD` | `STOREC_MOBILE` / `STOREC_PASSWORD` |
| Browser | headless | **visible** |
| Database checks | yes | no |

Two things differ on StoreC, both unavoidable:

- **The browser is visible.** StoreC sits behind a Cloudflare bot check that a
  headless browser never clears - it signs in and then sits on the login page
  with no menu. Headed, it goes straight through.
- **No database checks.** The StoreC database is not reachable from here (it is
  not on the server that holds DemoStore), so the two cross-checks - that the
  token really is the counter's, and that the session really reached the server
  - are skipped. Every browser and exe step is identical.

## What registration ticks

| Column | Ticked |
|---|---|
| Left | the first four — Is Allow Sales Person, Is Sync, Is Print Check, Declaration Slip Print |
| Middle | all five — Direct Point Redeem, Is Item Search, View Item Detail, Show Cost Price, View By Item Code |
| Right | nothing — left exactly as it comes |

Item Code Length is set to **4**, and the session opens with **0** opening cash.

## The log

Every step narrates itself, so it is clear what is happening and where it
stopped if it stops. Fetching the token is the slowest part and the least
obvious, so it reports each move:

```
[1/5] Collecting a fresh token from the back office
        opening https://demo-backoffice.example.com/ ...
        signing in ...
        POS > Setup > Counter Setup ...
        searching for the sami2 counter ...
        opening Generate Token ...
        pressing Generate New ...
        token received: 2112 characters, generated 2026-10-17 12:52:22
        matches the counter record
```

The token is read back from `pos.POSCounter` and compared with what the popup
showed, so a stale or half-generated token is caught before the exe is given it.

## Settings

At the top of `setup_tasks.py`: `COUNTER_ID` / `COUNTER_NAME`, `OPENING_CASH`,
`ITEM_CODE_LENGTH`, and the two checkbox lists. The employee credentials come
from `../.env` (`POS_USER_ID`, `POS_PASSWORD`) — never from this file.

## Notes

- The app must be installed; the reset works on the MSIX package, not on files.
- **Generate New** is pressed every time, so each run registers with a token
  that has never been used. Simply opening the popup shows the old token and
  does not create one.
- If no new session reaches the server the run says so rather than claiming
  success — the counter can be left in a state where the app opens a session
  only locally.
