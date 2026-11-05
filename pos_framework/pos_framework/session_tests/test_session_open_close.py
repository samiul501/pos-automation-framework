"""Session Open / Close - does a close actually reach the server?

Drives one full cycle on counter sami2 and then checks the server's own
record of it:

    reset -> token -> register -> login -> open session -> one sale
    -> LOG OUT without closing -> log back in -> Session Close

The logout in the middle is deliberate: it is the condition under which the
exe writes the close into its own database, marks it synced, shows the
cashier success, and never sends it. These tests fail while that is true and
pass once the close reaches the server.

Reproduction script and notes: reproduce_session_close_bug.py / README.md
Full write-up: ../backoffice/bug-reports/pos-session-close-not-saved/
"""
import os
import time

import allure
import pytest

import reproduce_session_close_bug as flow


@pytest.fixture(scope="module")
def cycle():
    """One complete session cycle, driven once for the whole module."""
    state = {}

    with allure.step("Reset the installed application"):
        flow.reset_app()

    with allure.step("Generate a fresh token for " + flow.COUNTER_NAME):
        token = flow.generate_token()
        state["token_length"] = len(token)

    with allure.step("Register the exe with that token"):
        win = flow.register_exe(token)
        state["win"] = win

    with allure.step("Log in as " + flow.EMPLOYEE):
        flow.login(win)
        state["title"] = win.child_window(auto_id="AppTitleBarText").window_text()

    with allure.step("How many sessions is the counter already carrying open?"):
        state["open_before"] = flow.open_session_count()
        allure.attach(str(state["open_before"]),
                      name="sessions already open on " + flow.COUNTER_NAME,
                      attachment_type=allure.attachment_type.TEXT)

    with allure.step("Open a session on " + flow.COUNTER_NAME):
        before = {r["CounterSessionId"] for r in flow.server_sessions(10)}
        flow.open_session(win)
        flow.shot(win, "03-session-open")
        new = []
        for _ in range(12):
            new = [r for r in flow.server_sessions(10)
                   if r["CounterSessionId"] not in before]
            if new:
                break
            time.sleep(5)
        state["opened"] = new[0] if new else None
        state["session_id"] = new[0]["CounterSessionId"] if new else None

    if state["session_id"] is None:
        # The open never reached the server. The exe usually has a local row
        # for it anyway - capture that, it is the whole diagnosis.
        state["sale_total"] = None
        state["server_after"] = None
        state["local_after"] = flow.local_session()
        yield state
        return

    with allure.step("One sale"):
        state["sale_total"] = flow.transaction(win)
        flow.shot(win, "04-sale")
        state["invoices"] = flow._query_invoices() if hasattr(flow, "_query_invoices") else None

    with allure.step("Log out WITHOUT closing the session"):
        flow.logout(win)
        flow.shot(win, "05-logged-out")

    with allure.step("The same employee logs back in"):
        flow.login(win)

    with allure.step("Lock Session -> Session Close -> Close Session"):
        flow.session_close(win)

    with allure.step("Read back what the server and the exe each recorded"):
        time.sleep(8)
        rows = flow.db._query(
            """SELECT CounterSessionId, StartDatetime, ClosingDatetime,
                      TotalInvoice, TotalSales
                 FROM pos.CounterSession WHERE CounterSessionId = ?""",
            [state["session_id"]])
        state["server_after"] = rows[0] if rows else None
        state["local_after"] = flow.local_session()

    yield state


def _attach(name, text):
    allure.attach(str(text), name=name,
                  attachment_type=allure.attachment_type.TEXT)


@allure.title("A session opened on the exe is recorded on the server")
@allure.description(
    "Open Session must reach the server. Once a counter has accumulated "
    "sessions that were never closed, the exe has been seen to create the "
    "new session only in its own database, with IsSync = 0, and carry on as "
    "though it had opened normally.")
def test_session_opens_on_the_server(cycle):
    if cycle["session_id"] is None:
        local, queue, app_log_rows = cycle["local_after"]
        _attach("sessions already open on the counter", cycle.get("open_before"))
        _attach("exe row for the session it believes it opened",
                "SessionCode      %s\n"
                "StartDatetime    %s\n"
                "ClosingDatetime  %s\n"
                "IsSync           %s"
                % ((local or {}).get("SessionCode"),
                   (local or {}).get("StartDatetime"),
                   (local or {}).get("ClosingDatetime"),
                   (local or {}).get("IsSync")))
        pytest.fail(
            "Open Session appeared to work on the exe, but no new row arrived "
            "in pos.CounterSession for counter %s. The exe holds the session "
            "locally as %s with IsSync=%s. The counter was already carrying %s "
            "session(s) left open."
            % (flow.COUNTER_NAME, (local or {}).get("SessionCode"),
               (local or {}).get("IsSync"), cycle.get("open_before")))

    _attach("session", "#%s opened at %s by user %s"
            % (cycle["session_id"],
               str(cycle["opened"]["StartDatetime"])[:19],
               cycle["opened"]["ActionById"]))
    _attach("sessions already open on the counter", cycle.get("open_before"))


@allure.title("A sale inside the session reaches the cart")
def test_sale_is_rung_up(cycle):
    if cycle["session_id"] is None:
        pytest.skip("no session was opened")
    total = cycle["sale_total"]
    assert total not in (None, "", "0", "0.00"), (
        "barcode %s did not ring up - check it is stocked in the counter's "
        "warehouse" % flow.BARCODE)
    _attach("cart total", total)


@allure.title("Session Close reaches the server after a logout")
@allure.description(
    "The exe is logged out between opening the session and closing it. "
    "The close must still arrive at the server - the exe must not report "
    "success for a close the server never accepted.")
def test_session_close_reaches_the_server(cycle):
    if cycle["session_id"] is None:
        pytest.skip("no session was opened")

    server = cycle["server_after"]
    local, queue, app_log_rows = cycle["local_after"]

    server_closed = bool(server and server["ClosingDatetime"])
    local_closed = bool(local and str(local.get("ClosingDatetime")) not in ("None", ""))

    _attach("server row", "#%s  ClosingDatetime = %s"
            % (cycle["session_id"],
               server["ClosingDatetime"] if server_closed else "NULL (still open)"))
    _attach("exe row",
            "SessionCode            %s\n"
            "ClosingDatetime        %s\n"
            "IsSync                 %s\n"
            "UserIdForSessionClose  %s\n"
            "unsent rows in queue   %s\n"
            "AppLog rows            %s"
            % ((local or {}).get("SessionCode"),
               (local or {}).get("ClosingDatetime"),
               (local or {}).get("IsSync"),
               (local or {}).get("UserIdForSessionClose"),
               queue, app_log_rows))

    if local_closed and not server_closed:
        pytest.fail(
            "Session #%s: the exe recorded the close at %s and set IsSync=%s, "
            "but pos.CounterSession.ClosingDatetime is still NULL. Nothing is "
            "queued for retry (%s unsent rows) and AppLog holds %s rows, so the "
            "close is lost silently and the session stays open for good."
            % (cycle["session_id"], (local or {}).get("ClosingDatetime"),
               (local or {}).get("IsSync"), queue, app_log_rows))

    assert server_closed, (
        "Session #%s is still open on the server after Session Close"
        % cycle["session_id"])


@allure.title("The session carries its invoice count and sales total")
@allure.description(
    "Every row in pos.CounterSession carries TotalInvoice = 0 and "
    "TotalSales = 0, including sessions that demonstrably hold invoices, so "
    "cash cannot be reconciled against a session.")
def test_session_totals_are_recorded(cycle):
    if cycle["session_id"] is None:
        pytest.skip("no session was opened")
    server = cycle["server_after"]
    assert server is not None, "the session row vanished from the server"

    _attach("totals", "TotalInvoice = %s, TotalSales = %s"
            % (server["TotalInvoice"], server["TotalSales"]))
    assert float(server["TotalInvoice"] or 0) > 0, (
        "Session #%s holds at least one invoice (cart total %s) but "
        "TotalInvoice is %s" % (cycle["session_id"], cycle["sale_total"],
                                server["TotalInvoice"]))
    assert float(server["TotalSales"] or 0) > 0, (
        "Session #%s holds at least one invoice (cart total %s) but "
        "TotalSales is %s" % (cycle["session_id"], cycle["sale_total"],
                              server["TotalSales"]))
