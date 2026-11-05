# ============================================================
# LOGIN - the one screen that is identical in both apps.
#
# Confirmed live: DemoStore and StoreB serve the same login form,
# same element ids (#loginMobileNo / #loginPassword / #loginButton)
# and the same Cloudflare Turnstile check, so this page object
# takes no per-app branches - only the URL and the credentials
# come from the profile.
# ============================================================

import time


class LoginPage(object):

    MOBILE = "#loginMobileNo"
    PASSWORD = "#loginPassword"
    SUBMIT = "#loginButton"

    def __init__(self, page, profile):
        self.page = page
        self.profile = profile

    def goto(self):
        self.page.goto(self.profile.base_url, wait_until="domcontentloaded")
        self.page.wait_for_selector(self.MOBILE, timeout=45000)
        return self

    def login(self, username=None, password=None):
        """Sign in and wait until the app itself is up - not merely until
        the click lands. A login that "worked" but left the shell still
        loading is the classic source of a first-test-only failure."""
        self.goto()
        self.page.fill(self.MOBILE, username or self.profile.username())
        self.page.fill(self.PASSWORD, password or self.profile.password())

        self.solve_human_check()
        self.page.click(self.SUBMIT)
        self.wait_until_signed_in()
        return self

    def solve_human_check(self, timeout_seconds=15):
        """Cloudflare Turnstile sits between the password field and the
        button. Its checkbox lives in a closed shadow root, so it cannot
        be targeted by selector - the only way in is to click where it
        renders, which is always just above the login button.

        If the button is already enabled there is nothing to solve, which
        is the common case on these dev hosts.

        The sleep here is deliberate and is the one place it is allowed:
        Turnstile verifies on its own clock and emits no DOM or network
        signal Playwright can wait on. It is a bounded poll, not a guess.
        """
        button = self.page.locator(self.SUBMIT)
        if button.is_enabled():
            return True

        password_box = self.page.locator(self.PASSWORD).bounding_box()
        button_box = button.bounding_box()
        if not password_box or not button_box:
            return False

        self.page.mouse.click(
            button_box["x"] + 20,
            (password_box["y"] + password_box["height"] + button_box["y"]) / 2,
        )

        for _ in range(timeout_seconds):
            if button.is_enabled():
                return True
            time.sleep(1)
        return False

    def wait_until_signed_in(self, timeout=60000):
        """Signed in means the navigation shell is present, not just that
        the login form went away."""
        self.page.wait_for_selector(
            ".menuContent, nav, [role='navigation']", timeout=timeout)
        self.page.wait_for_timeout(2000)
        return self

    def is_on_login_screen(self):
        return self.page.locator(self.MOBILE).count() > 0

    # ---- the hour-long lock -------------------------------------------

    CONFIRM_BUTTON = "Confirm password"

    def session_expired(self):
        """The app locks itself after an hour idle.

        It does NOT return to the login screen - it keeps the page and
        overlays "Your session has expired. Please confirm password to
        continue", with one password box and a Confirm button. Every menu
        request then answers 400, so a run that does not handle this sits
        waiting 45 seconds for a sidebar that will never appear, and
        reports a Playwright timeout that says nothing about the cause.
        """
        try:
            return "session has expired" in self.page.inner_text("body").lower()
        except Exception:
            return False

    def unlock_if_expired(self, timeout=30000):
        """Type the password back in and carry on. Returns True if it had
        to. Cheap to call before anything that expects the menu."""
        if not self.session_expired():
            return False

        box = self.page.locator("input[type='password']").first
        if not box.count():
            return False
        box.fill(self.profile.password())
        self.page.get_by_role(
            "button", name=self.CONFIRM_BUTTON, exact=False).first.click(force=True)
        try:
            self.page.wait_for_selector(".menuContent", timeout=timeout)
        except Exception:
            return False
        self.page.wait_for_timeout(1500)
        return True
