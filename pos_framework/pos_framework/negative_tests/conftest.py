# ============================================================
# NEGATIVE-FLOW SAFETY NET
#
# The negative+positive flow interleaves cases that deliberately
# provoke popups ("No item selected", "Customer Information Not
# Found", "Receive amount is less than Sale Amount", underpay /
# duplicate / print prompts...). If any ONE case leaves a modal
# open (or a number in the customer box), every case after it used
# to fail in turn - the leftover popup sat on top of the screen and
# ate the next case's clicks/keys.
#
# This autouse fixture makes each test self-protecting. BEFORE and
# AFTER every test it resets the screen to a clean state:
#   1. closes any popup still open (several rounds, Esc fallback),
#   2. clears a leftover customer number so the next case can't
#      concatenate onto it.
# So one failing test can never block or corrupt the next one -
# exactly the "close any popup, then start the next case clean"
# guarantee we want. It is best-effort and silent: it never fails a
# test by itself, and it never touches the app's title-bar close.
# ============================================================

import time

import pytest
from pywinauto.keyboard import send_keys

import pos_helpers as h


def _popup_button_present(main_win):
    for aid in h.POPUP_BUTTON_AUTO_IDS:
        try:
            if main_win.child_window(auto_id=aid, control_type="Button").exists(timeout=0):
                return True
        except Exception:
            pass
    return False


def _reset_screen(where):
    """Best-effort: dismiss every popup and clear the customer box so the
    next test starts clean. Never raises."""
    try:
        if not h.app_window_exists():
            return                       # app not up yet (e.g. before the first login test)
        main_win = h.get_main_window(timeout=5)

        # 1) Close any open popups - several rounds, because one popup can sit
        #    behind another, then an Esc nudge if a dialog button still lingers.
        closed = 0
        for _ in range(4):
            n = 0
            try:
                n = h.dismiss_any_popup(main_win)
            except Exception:
                pass
            closed += n
            if n == 0:
                break
        if _popup_button_present(main_win):
            try:
                send_keys("{ESC}")
                time.sleep(0.4)
                closed += h.dismiss_any_popup(main_win)
            except Exception:
                pass

        # 2) Clear a leftover customer number (only once no popup is in the
        #    way) so the next case does not type on top of it ("123" + "123").
        if not _popup_button_present(main_win):
            try:
                cf = main_win.child_window(auto_id="txtCustomer", control_type="Edit")
                if cf.exists(timeout=1):
                    cf.click_input()
                    cf.type_keys("^a{BACKSPACE}")
            except Exception:
                pass

        if closed:
            print("[popup-guard] closed %d leftover popup(s) %s the test" % (closed, where))
    except Exception as e:
        print("[popup-guard] skipped (%s): %s" % (where, str(e)[:80]))


@pytest.fixture(autouse=True)
def clear_popups_around_each_test():
    _reset_screen("before")
    yield
    _reset_screen("after")
