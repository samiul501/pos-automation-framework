# ============================================================
# APP PROFILE - the contract every back-office environment fills
# in, and the ONLY place the two apps are allowed to differ.
#
# WHY THIS LAYER EXISTS
# ---------------------
# The same business flow reaches the same screen by DIFFERENT
# paths in each app. Creating an item is, on paper, one test; in
# practice:
#
#   StoreB          Configuration -> Entity Master Data -> Item Profile -> "Add Item"
#   DemoStore  Configuration -> Item Profile                        -> "Add Item"
#
# and the master data behind it differs too (StoreB Head Office vs
# Dhanmondi Outlet, StoreB Warehouse vs DISPLAY). If those paths sit
# inside the page objects, every screen needs an if/else per app
# and the suite rots. So a page object asks the profile "how do I
# get to the item create screen here?" and the profile answers.
#
# A new environment therefore costs ONE file - no test changes.
#
# WHAT GOES IN A PROFILE
#   connection  base url + credentials (from .env, never hardcoded)
#   nav         the menu trail to each screen
#   buttons     the create/save button labels that differ per app
#   master      reference data that must already exist there
#   flags       app behaviours a test has to adapt to, not assert
#               away (e.g. DemoStore generates item codes itself,
#               so a test must not type one)
#   database    which SQL database backs this app, for verification
#
# WHAT DOES NOT GO IN A PROFILE
#   business rules. "A credit sale must not exceed the credit
#   limit" is true in both apps - that belongs in knowledge/ and in
#   the test. Only the mechanics of getting there live here.
# ============================================================

import os


class Profile(object):
    """One back-office environment. Subclasses fill in the class
    attributes; nothing here talks to a browser or a database."""

    # ---- identity ----
    key = None                  # short name used as APP=<key>
    label = None                # what a report should call it

    # ---- connection ----
    base_url = None
    username_env = None         # name of the .env key holding the user
    password_env = None
    database = None             # SQL database name, for cross-checks

    # ---- navigation ----
    # screen key -> the menu trail, outermost first. The trail is what a
    # person clicks; an empty list means "this screen is not reachable by
    # menu in this app" and the page object should say so rather than
    # silently fall back to a URL (a URL can render a different, stripped
    # form - see flags["menu_only_form_gating"]).
    nav = {}

    # screen key -> the label of the button that opens the create form
    buttons = {}

    # screen key -> how this app's form for that screen is built.
    #
    # This exists because the two apps do not merely reach the same form by
    # different menus - on some screens they are not the same form at all.
    # DemoStore's Item create is a react-select/Formik page whose controls
    # are found by wrapper id and which demands Supplier, Barcode and a
    # Category/Sub/Minor chain; StoreB's is an Ant Design page found by
    # accessible name that asks for none of those. An if/else in the page
    # object would have to grow a branch per app per screen, so instead each
    # app DESCRIBES its form and one filler walks the description:
    #
    #   "item_create": {
    #       "save": "SAVE",
    #       "fields": [
    #           {"kind": "text",   "target": "itemName", "value": "masterItemName"},
    #           {"kind": "select", "target": "uom",      "value": "uom"},
    #       ],
    #   }
    #
    # kind   how to drive the control - see BasePage.fill_form
    # target the input's name= / wrapper id / accessible name, per kind
    # value  which key of the test data dict feeds it
    forms = {}

    # ---- data that must already exist in this environment ----
    master = {}

    # ---- behaviours a test has to adapt to ----
    flags = {
        # the app generates item/partner codes itself, so a test must
        # leave code fields empty (DemoStore rejects a manual code)
        "auto_item_code": False,
        # reaching a create form by URL renders it without the
        # permission-gated fields; the menu route is mandatory
        "menu_only_form_gating": False,
        # a partner's address must be pushed into the list with "Add List"
        # before the form will save
        "address_list_required": True,
    }

    # ---- credentials, read at call time so .env edits take effect ----
    @classmethod
    def username(cls):
        return os.environ.get(cls.username_env, "")

    @classmethod
    def password(cls):
        return os.environ.get(cls.password_env, "")

    # ---- helpers the page objects use ----
    @classmethod
    def trail(cls, screen):
        """The menu trail to `screen`. Raises with a readable message
        rather than returning None, so a missing mapping fails where it
        is caused instead of deep inside a click."""
        if screen not in cls.nav:
            raise KeyError(
                "profile %r has no nav trail for screen %r - add it to "
                "profiles/%s.py" % (cls.key, screen, cls.key))
        return list(cls.nav[screen])

    @classmethod
    def button(cls, screen):
        if screen not in cls.buttons:
            raise KeyError(
                "profile %r has no create-button label for screen %r" % (cls.key, screen))
        return cls.buttons[screen]

    @classmethod
    def form(cls, screen):
        """How this app builds the form for `screen`."""
        if screen not in cls.forms:
            raise KeyError(
                "profile %r does not describe the %r form - add forms[%r] to "
                "profiles/%s.py" % (cls.key, screen, screen, cls.key))
        return cls.forms[screen]

    @classmethod
    def knows_form(cls, screen):
        return bool(cls.forms.get(screen))

    @classmethod
    def data(cls, *path, **kwargs):
        """master data lookup: profile.data('employee', 'warehouse')."""
        node = cls.master
        for part in path:
            if not isinstance(node, dict) or part not in node:
                if "default" in kwargs:
                    return kwargs["default"]
                raise KeyError("profile %r has no master data at %s"
                               % (cls.key, " -> ".join(str(p) for p in path)))
            node = node[part]
        return node

    @classmethod
    def has(cls, *path):
        """True if this environment declares master data at `path`.

        Tests ask this before running, so a screen whose reference data
        has not been filled in for an app SKIPS with a message naming the
        key to add - instead of failing halfway through a form with
        "option not found", which reads like a product bug when it is
        only a gap in the profile."""
        node = cls.master
        for part in path:
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    @classmethod
    def knows_screen(cls, screen):
        """True if this environment declares a menu trail for `screen`."""
        return bool(cls.nav.get(screen))

    @classmethod
    def flag(cls, name):
        return cls.flags.get(name, False)

    @classmethod
    def describe(cls):
        return "%s (%s)" % (cls.label or cls.key, cls.base_url)
