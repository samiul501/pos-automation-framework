# ============================================================
# WHAT A TEST NEEDS FROM ITS ENVIRONMENT
#
# The same test runs against two apps, and the two apps are not
# equally mapped out: DemoStore's Language Configuration trail
# and StoreB's warehouse name were each read off a live app, and
# what has not been read is not in the profile.
#
# A test that just runs anyway fails deep inside a form with
# "no option 'None' in #office", which reads like a product bug.
# So every test declares up front what it needs, and if this
# environment has not been taught that yet the test SKIPS with
# the exact profile key to add.
#
#   requires(profile, screen="customer_create",
#            data=[("customer", "territory")])
#
# A skip here means "nobody has mapped this screen for this app
# yet" - it is a to-do, not a pass. The report shows it as such.
# ============================================================

import pytest


def requires(profile, screen=None, button=False, form=False, data=()):
    """Skip unless this profile declares everything the test needs."""
    missing = []

    if screen and not profile.knows_screen(screen):
        missing.append("nav[%r] - the menu trail to the screen" % screen)
    if screen and button and screen not in profile.buttons:
        missing.append("buttons[%r] - the label of the create button" % screen)
    if screen and form and not profile.knows_form(screen):
        missing.append("forms[%r] - which fields this app's form has" % screen)

    for path in data:
        path = (path,) if isinstance(path, str) else tuple(path)
        if not profile.has(*path):
            missing.append("master[%s]" % "][".join(repr(p) for p in path))

    if missing:
        pytest.skip(
            "%s has not been mapped for this screen yet - add to "
            "profiles/%s.py:\n  %s" % (profile.label or profile.key,
                                       profile.key, "\n  ".join(missing)))
