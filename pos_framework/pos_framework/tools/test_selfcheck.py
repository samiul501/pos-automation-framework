# ============================================================
# The self check as a pytest test, so it can run in the same
# report as everything else and fail a run before the exe is
# even launched.
#
#   python -m pytest tools/test_selfcheck.py -q
#
# It needs no exe, no browser and no database - if this one
# fails, nothing else is worth running.
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import selfcheck


def test_framework_selfcheck():
    result = selfcheck.run()
    if not result.ok:
        report = "\n".join("[%s] %s" % (area, message) for area, message in result.problems)
        raise AssertionError(
            "the framework itself has %d problem(s) - fix these before running any suite:\n%s"
            % (len(result.problems), report)
        )
