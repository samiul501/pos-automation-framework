# ============================================================
# PROFILE REGISTRY - picks the environment a run targets.
#
#   APP=demostore python -m pytest backoffice/tests
#   APP=storeb         python -m pytest backoffice/tests
#
# Default is demostore: it is the environment the rest of this
# repo (the exe suites, db_helpers, the dashboard) already points
# at, so an unqualified run stays inside one world.
# ============================================================

import os

from backoffice.profiles.storeb import StoreB
from backoffice.profiles.demostore import DemoStore

PROFILES = {
    DemoStore.key: DemoStore,
    StoreB.key: StoreB,
}

DEFAULT = DemoStore.key


def get(key=None):
    """The profile for `key`, or for $APP, or the default."""
    name = (key or os.environ.get("APP") or DEFAULT).strip().lower()
    if name not in PROFILES:
        raise SystemExit(
            "unknown APP %r - choose one of: %s" % (name, ", ".join(sorted(PROFILES))))
    return PROFILES[name]


def names():
    return sorted(PROFILES)
