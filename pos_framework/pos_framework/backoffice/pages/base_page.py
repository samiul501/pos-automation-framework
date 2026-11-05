# ============================================================
# BASE PAGE - reaching a screen the way a person reaches it.
#
# Every back-office page object inherits this. Its job is the
# part that differs between apps, and it does that by asking the
# profile for the menu trail rather than hardcoding one:
#
#   StoreB          Configuration -> Entity Master Data -> Item Profile
#   DemoStore  Configuration -> Item Profile
#
#   self.open("item_create")   works on both
#
# WHY NOT JUST page.goto(url)
# ---------------------------
# Because on DemoStore a create form reached by URL renders
# WITHOUT its permission-gated fields - Credit Limit, Credit Days,
# Territory and Customer Point are simply absent, and a test then
# "passes" having filled a form that was never the real one. The
# menu route loads the permissions first. Profiles that behave
# this way set flags["menu_only_form_gating"], and open() refuses
# to fall back to a URL for them.
#
# The sidebar also swallows ordinary clicks: a sibling <ul>
# overlays the entries, so every menu click here is force=True.
# ============================================================


class BasePage(object):

    # a menu entry renders as this in both apps
    MENU_ENTRY = ".menuContent"
    SETTLE_MS = 2000

    def __init__(self, page, profile):
        self.page = page
        self.profile = profile

    # ---- navigation -------------------------------------------------

    def goto_app(self, path=""):
        """Land on the app and make sure it is actually usable.

        Every navigation in this suite goes through here, because a saved
        session older than an hour comes back locked: the app keeps the
        page but overlays a password confirmation, and every menu request
        answers 400. Without this the next step waits 45 seconds for a
        sidebar that is never coming.
        """
        url = self.profile.base_url.rstrip("/") + ("/" + path.lstrip("/") if path else "/")
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(2000)

        from backoffice.pages.login_page import LoginPage
        LoginPage(self.page, self.profile).unlock_if_expired()
        return self

    def open(self, screen):
        """Walk the profile's menu trail to `screen`, then press the
        screen's create button if the profile names one."""
        trail = self.profile.trail(screen)
        if not trail:
            raise AssertionError(
                "%s does not expose %r through the menu" % (self.profile.key, screen))

        self.goto_app()
        self.page.wait_for_selector(self.MENU_ENTRY, timeout=45000)
        self.page.wait_for_timeout(self.SETTLE_MS)

        for step in trail:
            self.click_menu(step)

        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def click_menu(self, label):
        """Click one menu entry. Tries the menu container first, then a
        plain link - the last level of a trail is an <a>, the ones above
        it are expandable <div>s."""
        entry = self.page.locator(self.MENU_ENTRY, has_text=label).first
        if entry.count():
            entry.click(force=True)
            self.page.wait_for_timeout(1500)
            return self

        link = self.page.get_by_role("link", name=label, exact=True).first
        if link.count():
            link.click(force=True)
            self.page.wait_for_timeout(self.SETTLE_MS)
            return self

        raise AssertionError(
            "menu entry %r not found on %s - the trail in profiles/%s.py is out of date"
            % (label, self.profile.key, self.profile.key))

    def press_create(self, screen):
        """Press the button that opens the create form (its label differs
        per app: 'Add Item' vs 'Customer')."""
        label = self.profile.button(screen)
        self.page.get_by_role("button", name=label, exact=False).first.click(force=True)
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def expand_sections(self):
        """Open every collapsed block on a create form.

        These forms fold part of their fields behind a "View Details"
        toggle. The fields are still there and still required - they are
        simply not visible, so a fill waits for something that will never
        appear and times out saying nothing about a collapsed section.

        The toggles give no clue which way they point: the same control
        opens a closed block and closes an open one. So each click is
        judged by its effect - if it left FEWER controls on screen it
        closed something, and it is clicked again to put it back.
        """
        def visible_controls():
            return self.page.evaluate(
                """() => [...document.querySelectorAll(
                        'input, select, textarea, [class*="-container"]')]
                     .filter(e => e.offsetParent || e.getClientRects().length).length""")

        toggles = self.page.get_by_text("View Details", exact=False)
        for index in range(toggles.count()):
            before = visible_controls()
            try:
                toggles.nth(index).click(force=True)
                self.page.wait_for_timeout(900)
            except Exception:
                continue
            if visible_controls() < before:
                try:
                    toggles.nth(index).click(force=True)
                    self.page.wait_for_timeout(900)
                except Exception:
                    pass
        self.page.wait_for_timeout(1000)
        return self

    def open_create(self, screen):
        return self.open(screen).press_create(screen).expand_sections()

    # ---- filling a form the way this app builds it -------------------

    def fill_form(self, screen, data):
        """Fill `screen`'s form by walking the recipe in the profile.

        The recipe, not this method, is where the two apps differ - see
        Profile.forms. Each entry says how to drive one control:

          text / number        an <input name="..."> or <textarea>
          select               a react-select, found by its wrapper id
          sticky_select        the same, but re-checked because this form
                               re-renders selections away (Supplier et al.)
          search_select        a react-select that only loads options once
                               you type - target is the wrapper id
          antd_text            an Ant Design textbox, found by its
                               accessible name (which includes the label's
                               trailing affordance text, e.g.
                               "* UOM See All plus" - dropping it stops the
                               locator matching)
          antd_select          an Ant Design combobox, by accessible name
          antd_search_select   the same, typing first

        An entry may carry "optional": True to be skipped when the data has
        no value for it, and "skip_if_flag": "<name>" to be skipped where a
        profile flag says the app will not accept it (that is how the item
        code is left alone on an auto-item-code account).
        """
        page = self.page
        for field in self.profile.form(screen).get("fields", []):
            if field.get("skip_if_flag") and self.profile.flag(field["skip_if_flag"]):
                continue

            value = data.get(field["value"]) if "value" in field else field.get("const")
            if value is None:
                if field.get("optional"):
                    continue
                raise AssertionError(
                    "the %r form wants %r for %s, but the test data has no such key "
                    "(keys: %s)" % (screen, field.get("value"), field.get("target"),
                                    ", ".join(sorted(data))))

            kind = field["kind"]
            target = field["target"]
            # What to type into a picker that only fetches once you type.
            # "query" is a fixed string; "query_value" names another key of
            # the test data, which is how a profile can say "search for the
            # supplier with THIS string and expect THAT option back".
            query = field.get("query")
            if field.get("query_value"):
                query = data.get(field["query_value"])

            if kind in ("text", "number"):
                self.fill(target, value)
            elif kind == "select":
                try:
                    self.select_option(target, str(value))
                except AssertionError:
                    # An optional select that offers nothing is a field the
                    # app no longer populates - report it and move on rather
                    # than failing the whole form on it.
                    if not field.get("optional"):
                        raise
                    print("   (skipped %s - it offered no options)" % target)
            elif kind == "sticky_select":
                self.select_sticky_option(target, str(value))
            elif kind == "search_select":
                self.search_option(target, query or str(value)[:3], str(value))
            elif kind == "placeholder_text":
                page.get_by_placeholder(target).fill(str(value))
            elif kind == "named_select":
                self._pick_in_container(
                    page.locator(".col-lg-3, .col-lg-4, .col-lg-6, .col-lg-12").filter(
                        has=page.locator('input[name="%s"]' % target)).get_by_role("combobox"),
                    query, str(value))
            elif kind == "placeholder_select":
                self._pick_in_container(
                    page.locator(".css-b62m3t-container").filter(
                        has=page.get_by_text(target, exact=True)),
                    query, str(value))
            elif kind == "antd_text":
                page.get_by_role(
                    "textbox", name=target, exact=field.get("exact", False)).fill(str(value))
            elif kind == "antd_select":
                page.get_by_role(
                    "combobox", name=target, exact=field.get("exact", False)).click()
                page.get_by_role("option", name=str(value), exact=True).click()
                page.wait_for_timeout(400)
            elif kind == "antd_search_select":
                page.get_by_role(
                    "combobox", name=target, exact=field.get("exact", False)).click()
                page.keyboard.type(str(query or value))
                page.wait_for_timeout(1200)
                page.get_by_role("option", name=str(value)).first.click()
                page.wait_for_timeout(400)
            else:
                raise AssertionError("unknown field kind %r in forms[%r]" % (kind, screen))

        return self

    def _pick_in_container(self, control, query, option_text):
        """Open a react-select that has no id and no accessible name, then
        choose an option - typing first where the list only loads on input.

        The Purchase Order screen is the reason this exists: it is a
        Formik/react-select form with no aria wiring at all, so its
        controls can only be reached through the markup around them.
        """
        control.first.click(force=True)
        self.page.wait_for_timeout(600)
        if query:
            self.page.keyboard.type(str(query), delay=110)
            self.page.wait_for_timeout(2000)
        self.page.get_by_role("option", name=option_text).first.click(force=True)
        self.page.wait_for_timeout(600)
        return self

    def save_form(self, screen):
        """Press this app's save button for `screen` (StoreB says "Save",
        DemoStore says "SAVE" - and the two are different buttons, not a
        casing quirk of the locator)."""
        return self.save(self.profile.form(screen).get("save", "SAVE"))

    def validation_errors(self):
        """Whatever the form is complaining about, in the order shown.

        Worth reporting alongside a failure: "Item Sub Category is required"
        and "Auto itemcode is active for this account" are very different
        problems, and without this both read as "save did nothing"."""
        found = self.page.eval_on_selector_all(
            "[class*='error'], .invalid-feedback, .text-danger",
            "els => els.map(e => (e.innerText || '').trim())")
        return [t for t in dict.fromkeys(found) if t]

    # ---- small shared helpers ---------------------------------------

    def select_option(self, container_id, option_text, attempts=3):
        """Pick a value from one of the app's react-selects.

        force=True on both the control and the option is not optional: a
        transparent overlay div sits on top of these widgets and eats
        ordinary clicks. The retry covers options that arrive a beat
        after the control opens.
        """
        selector = "#" + container_id if not container_id.startswith("#") else container_id
        self.page.wait_for_selector(selector, timeout=15000)
        option_selector = "[class*='-option'], div[role='option']"

        for attempt in range(1, attempts + 1):
            self.page.click(selector, force=True)
            self.page.wait_for_timeout(800 + 400 * attempt)
            match = self.page.locator(option_selector, has_text=option_text)
            if match.count():
                match.first.click(force=True)
                self.page.wait_for_timeout(800)
                return self
            if attempt == attempts:
                seen = [t.strip() for t in self.page.eval_on_selector_all(
                    option_selector, "els => els.map(e => e.innerText)") if t.strip()]
                raise AssertionError(
                    "no option %r in #%s; options seen: %r" % (option_text, container_id, seen[:10]))
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)
        return self

    def select_sticky_option(self, container_id, option_text, attempts=3):
        """select_option, but it keeps going until the value actually stuck.

        Some forms - Supplier, Other Partner - re-render in the background
        after their master data finishes loading, even once the page looks
        settled. That re-render can silently DISCARD a selection made a
        moment earlier: Playwright saw the click succeed, no error was
        raised, and the control quietly reverted to its placeholder. So a
        click that did not throw is not proof; the wrapper showing the
        chosen text is. Diagnosed on Supplier create in the source suite.
        """
        selector = "#" + container_id if not container_id.startswith("#") else container_id
        wrapper = self.page.locator(selector)
        option_selector = "[class*='-option'], div[role='option']"
        self.page.wait_for_selector(selector, timeout=15000)

        for attempt in range(1, attempts + 1):
            wrapper.click(force=True)
            self.page.wait_for_timeout(800 + 400 * attempt)

            match = self.page.locator(option_selector, has_text=option_text)
            if match.count():
                match.first.click(force=True)
                self.page.wait_for_timeout(1000)
                if wrapper.get_by_text(option_text, exact=True).count():
                    return self
                # It reverted. Fall through and pick it again.
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)

        raise AssertionError(
            "selecting %r in #%s did not stick after %d attempts - the form "
            "keeps re-rendering it away" % (option_text, container_id, attempts))

    def search_option(self, container_id, query, option_text=None, attempts=3):
        """Same, for the selects that only load options once you type."""
        want = option_text or query
        selector = "#" + container_id if not container_id.startswith("#") else container_id
        option_selector = "[class*='-option'], div[role='option']"
        self.page.wait_for_selector(selector, timeout=15000)

        for attempt in range(1, attempts + 1):
            self.page.click(selector, force=True)
            self.page.wait_for_timeout(700)
            self.page.keyboard.type(str(query), delay=110)
            self.page.wait_for_timeout(1500 * attempt)
            match = self.page.locator(option_selector, has_text=want)
            if match.count():
                match.first.click(force=True)
                self.page.wait_for_timeout(800)
                return self
            if attempt == attempts:
                seen = [t.strip() for t in self.page.eval_on_selector_all(
                    option_selector, "els => els.map(e => e.innerText)") if t.strip()]
                raise AssertionError(
                    "searching %r in #%s found nothing; options seen: %r" % (query, container_id, seen[:10]))
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)
        return self

    def fill(self, field_name, value):
        field = self.page.locator("input[name='%s'], textarea[name='%s']"
                                  % (field_name, field_name)).first
        field.click()
        field.fill("" if value is None else str(value))
        self.page.wait_for_timeout(200)
        return self

    def value_of(self, field_name):
        field = self.page.locator("input[name='%s']" % field_name).first
        return field.input_value() if field.count() else None

    def wait_for_field(self, field_name, timeout=15000):
        """Wait for one field to exist, and say whether it ever did.

        These forms render progressively - the permission-gated fields in
        particular arrive a beat after the rest - so asking "is it there?"
        the instant the form opens answers no for a field that is simply
        not painted yet.
        """
        try:
            self.page.wait_for_selector(
                "input[name='%s'], textarea[name='%s']" % (field_name, field_name),
                timeout=timeout, state="attached")
            return True
        except Exception:
            return False

    def has_field(self, field_name):
        return self.page.locator("input[name='%s'], textarea[name='%s']"
                                 % (field_name, field_name)).count() > 0

    def save(self, label="SAVE"):
        self.page.get_by_role("button", name=label, exact=False).first.click(force=True)
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    def toast(self, timeout_seconds=20):
        """Wait for the app's notification and return its text.

        Reading it once after a fixed sleep is not enough - the toast is
        transient and a save that had in fact succeeded came back as an
        empty string more than once. Poll until it shows or time runs out.
        """
        selectors = ".Toastify__toast-body, [class*='toast'], [role='alert']"
        deadline = timeout_seconds * 10
        for _ in range(deadline):
            texts = [t.strip() for t in self.page.eval_on_selector_all(
                selectors, "els => els.map(e => (e.innerText || '').trim())") if t.strip()]
            if texts:
                return " | ".join(dict.fromkeys(texts))
            self.page.wait_for_timeout(100)
        return ""
