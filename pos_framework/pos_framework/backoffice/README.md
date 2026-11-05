# Back office suite

Menu-driven checks of the POS App back office, written once and run
against **either** environment:

| app | url | database |
|---|---|---|
| `demostore` | https://demo-backoffice.example.com/ | DemoStore |
| `storeb` | https://storeb-backoffice.example.com/ | SME |

    cd pos_framework/pos_framework
    APP=demostore ..\venv\Scripts\python -m pytest backoffice -c backoffice/pytest.ini
    APP=storeb         ..\venv\Scripts\python -m pytest backoffice -c backoffice/pytest.ini

or from the dashboard: **Back Office - DemoStore** / **Back Office - StoreB**.

Useful flags: `-m smoke` (harness only), `--headed` (watch it), `--fresh-login`
(discard the saved session), `--app storeb` (instead of the env var).

## How one suite serves two apps

The business flow is the same in both; only the way you reach it differs.

    StoreB          Configuration -> Entity Master Data -> Item Profile -> "Add Item"
    DemoStore  Configuration -> Item Profile                       -> "Add Item"

So a page object never hardcodes a path. It asks the profile:

```python
class ItemCreatePage(BasePage):
    def open_form(self):
        return self.open_create("item_create")      # works on both
```

and each environment answers for itself in `profiles/<app>.py`:

```python
nav     = {"item_create": ["Configuration", "Item Profile"]}
buttons = {"item_create": "Add Item"}
master  = {"office": "Dhanmondi Outlet", "warehouse": "DISPLAY"}
flags   = {"auto_item_code": True, "menu_only_form_gating": True}
```

**A new environment costs one file.** No test changes.

## Layout

    backoffice/
      profiles/      base.py + one file per environment  <- all per-app differences
      pages/         page objects (login_page, base_page, then one per screen)
      tests/         the tests; mirror pages/
      utils/         data generators
      knowledge/     per module: what it does and the rules it must obey
      test_data/     reference data that must already exist
      conftest.py    profile, login-once session, logged-in page
      pytest.ini     Playwright options - deliberately NOT at the repo root

## Two rules worth knowing before writing a test

**Navigate by menu, never by URL.** On DemoStore a create form opened by
URL renders *without* its permission-gated fields - Credit Limit, Credit
Days, Territory and Customer Point are simply absent. A test that fills
that form passes while having tested nothing. Profiles where this happens
set `flags["menu_only_form_gating"]`, and `BasePage.open()` refuses to fall
back to a URL.

**Force every click on a menu or a react-select.** A transparent overlay
sits over both and swallows ordinary clicks. `BasePage` already does this -
use its helpers (`select_option`, `search_option`) rather than clicking
directly.

## Fixtures

| fixture | what it gives you |
|---|---|
| `profile` | the environment under test - trails, master data, flags |
| `page` | a browser page already signed in to it |
| `reachable_profile` | same as `profile`, but skips if the host is unreachable |

The session signs in **once** per app and reuses the cookies from
`auth/<app>-user.json`; `--fresh-login` throws them away.

`devmgm` only resolves on the office VPN. Off it, the browser tests skip
with "not reachable" rather than failing - that is deliberate, so a
DemoStore-only machine still gets a clean run.

## Adding a screen

1. Add its menu trail and create-button label to **both** profiles.
2. Write the page object on `BasePage` and use `self.open_create("<screen>")`.
3. Write the test against `page` and `profile` - no app names in the test.
4. Write the module's rules into `knowledge/<module>.md` so the next person
   knows what the screen is supposed to guarantee.

## What is not here

The exe suites (`positive_tests`, `negative_tests`, `audit_tests`,
`credit_tests`, `client_issues`) are unchanged and still run exactly as
before. This folder only adds the back-office half; nothing above it moved.
