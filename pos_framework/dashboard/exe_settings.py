# ============================================================
# EXE SETTINGS - read/write the handful of switches the POS exe
# keeps in its OWN local cache, so they can be seen and flipped
# from the dashboard instead of by hand in a SQLite browser.
#
# WHY THIS EXISTS
# ---------------
# `IsCustomerGroupInProductDiscount` decides whether a product
# discount is limited to its assigned customer group (true) or
# handed to everyone (false). The automation's expected totals
# assume true. The switch lives NOWHERE on the server - not in
# DemoStore, not in any other database on that host (all
# searched 2026-09-21) - only in the exe's cached settings row:
#
#   %LOCALAPPDATA%\Packages\<pos package family>\LocalState\
#       Database\POS.1.01.db  ->  TblSettings (intID = 1)
#
# A reinstall / counter re-registration (e.g. the MSIX auto-update)
# writes that row fresh with the value false; a plain logout/login
# leaves it alone. So the practical fix is: flip it here, restart
# the exe. runner.py can also re-assert it right before every exe
# suite (after the exe has been closed), so a reinstall can never
# silently change what the suites are testing.
#
# The invoice template names (strInvoiceName / strInvoiceRePrintName)
# sit in the same row - and ALSO on the server (dbo.Account
# .strInvoiceName / .strInvoiceRePrintName, account-level, so every
# counter of the account). The exe prints whatever its cache says,
# the cache is filled from the server at registration - so a switch
# must write BOTH or the wrong invoice keeps printing (that is
# exactly what happened before). set_invoice_template() does both.
# The choices are read off the installed exe's Assets\RDLC folder,
# paired sale <-> reprint by name, so a new build's templates show
# up on their own.
# ============================================================

import os
import re
import sys
import glob
import time
import sqlite3
import subprocess

_POS_FRAMEWORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pos_framework")

PACKAGE_NAME = "CF9BD7D4-0F9A-4730-8950-05D032861D46"
GROUP_FLAG = "IsCustomerGroupInProductDiscount"

_FIELDS = [
    GROUP_FLAG, "strInvoiceName", "strInvoiceRePrintName",
    "StrCounterName", "StrBranchName", "StrOfficeName", "intCounterId", "intAccountId",
]


def find_local_db():
    """The exe's cached-settings SQLite. There can be more than one package
    hash on a machine (each install signed with a different certificate
    gets its own LocalState); the one written most recently is the live
    one."""
    pattern = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Packages", PACKAGE_NAME + "_*",
        "LocalState", "Database", "POS.1.01.db",
    )
    paths = glob.glob(pattern)
    if not paths:
        return None
    return max(paths, key=lambda p: os.path.getmtime(p))


def _package_hash(db_path):
    parts = db_path.replace("/", "\\").split("\\")
    for p in parts:
        if p.startswith(PACKAGE_NAME + "_"):
            return p[len(PACKAGE_NAME) + 1:]
    return ""


# Each PowerShell round trip costs ~4s on this machine, and read() used to
# make three of them (version, install location, running pid) plus a directory
# scan - 12.7s per call, while the dashboard polls every 10s. The card
# therefore never finished loading and sat on "reading exe cache...". One
# combined call, cached briefly, brings it under a second.
_PS_CACHE = {"at": 0.0, "value": (None, None, False)}
_PS_CACHE_SECONDS = 20

_TEMPLATE_CACHE = {"location": None, "value": []}


def _probe(force=False):
    """(version, install location, exe running) in ONE PowerShell call."""
    now = time.time()
    if not force and now - _PS_CACHE["at"] < _PS_CACHE_SECONDS:
        return _PS_CACHE["value"]
    value = (None, None, False)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$p = Get-AppxPackage | Where-Object { $_.PackageFamilyName -like '" + PACKAGE_NAME + "*' } "
             "| Select-Object -First 1; "
             "$proc = Get-Process POS -ErrorAction SilentlyContinue | Select-Object -First 1; "
             "$p.Version; $p.InstallLocation; if ($proc) { 'RUNNING' } else { 'STOPPED' }"],
            capture_output=True, text=True, timeout=25,
        )
        lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
        version = lines[0] if lines else None
        location = lines[1] if len(lines) > 1 else None
        running = any(x == "RUNNING" for x in lines)
        value = (version, location, running)
    except Exception:
        pass
    _PS_CACHE["at"] = now
    _PS_CACHE["value"] = value
    return value


def _installed_package():
    """(version, install location) of the POS package Windows has now."""
    version, location, _running = _probe()
    return version, location


def installed_version():
    return _probe()[0]


# ---- invoice templates ----------------------------------------------

def _reprint_name_for(sale):
    """The reprint .rdlc that goes with a sale .rdlc, by the naming the
    builds actually use:  rptInvoiceV10 -> rptInvoiceRePrintV10,
    rptInvoice-yamaan -> rptInvoiceRePrint-yamaan, RPTInvoiceAditi ->
    RPTInvoiceAditiRePrint, DS_V2_FullDetails -> DS_V2_FullDetailsRePrint."""
    stem = sale[:-5] if sale.lower().endswith(".rdlc") else sale
    cands = []
    m = re.match(r"^(rptInvoice)(.*)$", stem)
    if m:
        cands.append(m.group(1) + "RePrint" + m.group(2))
    cands.append(stem + "RePrint")
    return [c + ".rdlc" for c in cands]


def _template_label(sale):
    stem = sale[:-5]
    m = re.match(r"^rptInvoice(V\d+)$", stem)
    if m:
        return m.group(1)
    m = re.match(r"^rptInvoice-(.+)$", stem)
    if m:
        return m.group(1).capitalize()
    m = re.match(r"^RPTInvoice(.+)$", stem)
    if m:
        return m.group(1) + " (new)"
    if stem == "rptInvoice":
        return "Default (rptInvoice)"
    return stem


def list_invoice_templates():
    """Every sale template shipped in the installed exe that has a matching
    reprint template: [{label, sale, reprint}], V-numbers first (newest
    first), then the named ones."""
    _version, location = _installed_package()
    if location and _TEMPLATE_CACHE["location"] == location:
        return _TEMPLATE_CACHE["value"]
    folder = os.path.join(location, "Assets", "RDLC") if location else None
    if not folder or not os.path.isdir(folder):
        return []
    names = {n for n in os.listdir(folder) if n.lower().endswith(".rdlc")}
    lower = {n.lower(): n for n in names}
    out = []
    for n in sorted(names):
        low = n.lower()
        if "reprint" in low or "backup" in low or "hold" in low:
            continue
        if not (low.startswith("rptinvoice") or low.startswith("ds_") or "inclusive" in low):
            continue
        reprint = next((lower[c.lower()] for c in _reprint_name_for(n) if c.lower() in lower), None)
        if reprint:
            out.append({"label": _template_label(n), "sale": n, "reprint": reprint})

    def order(t):
        m = re.match(r"^V(\d+)$", t["label"])
        return (0, -int(m.group(1))) if m else (1, t["label"].lower())
    out.sort(key=order)
    _TEMPLATE_CACHE["location"] = location
    _TEMPLATE_CACHE["value"] = out
    return out


def _server_invoice(account_id):
    """dbo.Account's template names for this account (None if no DB)."""
    if _POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, _POS_FRAMEWORK_DIR)
    import db_helpers as db
    if not db.is_available():
        return None
    rows = db._query("SELECT strInvoiceName, strInvoiceRePrintName FROM dbo.Account WHERE AccoutId = ?", [account_id])
    return rows[0] if rows else None


def exe_running():
    return _probe()[2]


def read():
    """Everything the UI card needs, in one dict. Never raises - a missing
    cache (exe never registered on this machine) comes back as ok=False."""
    db_path = find_local_db()
    out = {"ok": False, "db_path": db_path, "package": None, "version": installed_version(),
           "exe_running": exe_running(), "settings": {}, "error": None}
    if not db_path:
        out["error"] = "POS exe local cache not found (is the exe installed and registered?)"
        return out
    out["package"] = _package_hash(db_path)
    try:
        conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT " + ", ".join(_FIELDS) + " FROM TblSettings WHERE intID = 1").fetchone()
        finally:
            conn.close()
        if row is None:
            out["error"] = "TblSettings is empty - the exe has not registered a counter yet"
            return out
        out["settings"] = {k: row[k] for k in _FIELDS}
        out["settings"][GROUP_FLAG] = bool(row[GROUP_FLAG])
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)[:200]
        return out
    try:
        out["templates"] = list_invoice_templates()
    except Exception as e:
        out["templates"] = []
        out["templates_error"] = str(e)[:200]
    try:
        out["server_invoice"] = _server_invoice(out["settings"].get("intAccountId"))
    except Exception as e:
        out["server_invoice"] = None
        out["server_error"] = str(e)[:200]
    return out


def set_group_flag(value):
    """Writes IsCustomerGroupInProductDiscount (True/False). Returns
    (ok, message). Works while the exe is running too (SQLite WAL), but
    the exe only picks it up on its next start - the caller says so."""
    db_path = find_local_db()
    if not db_path:
        return False, "POS exe local cache not found"
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("UPDATE TblSettings SET " + GROUP_FLAG + " = ? WHERE intID = 1", (1 if value else 0,))
            conn.commit()
            now = conn.execute("SELECT " + GROUP_FLAG + " FROM TblSettings WHERE intID = 1").fetchone()
        finally:
            conn.close()
        if now is None or bool(now[0]) != bool(value):
            return False, "write did not stick (TblSettings row missing?)"
        return True, GROUP_FLAG + " = " + ("ON" if value else "OFF")
    except Exception as e:
        return False, str(e)[:200]


def enforce_group_flag_on():
    """For runner.py: make sure the flag is ON before an exe suite starts.
    Returns a one-line message for the run log."""
    state = read()
    if not state["ok"]:
        return "group-discount flag: could not read exe cache (" + str(state["error"]) + ")"
    if state["settings"].get(GROUP_FLAG):
        return "group-discount flag already ON (" + GROUP_FLAG + " = 1)"
    ok, msg = set_group_flag(True)
    return ("group-discount flag was OFF - set to ON before the run" if ok
            else "group-discount flag: FAILED to set ON (" + msg + ")")


def invalidate_cache():
    """After a write, or after a reinstall, force the next read to re-probe."""
    _PS_CACHE["at"] = 0.0
    _TEMPLATE_CACHE["location"] = None


def set_invoice_template(sale, reprint):
    """Switches the print invoice to the given sale/reprint .rdlc pair in
    BOTH places the exe depends on: the server row (dbo.Account for the
    account this counter belongs to) and the exe's local cache. Only
    names that exist in the installed exe are accepted, so a typo can
    never leave the exe with a template it cannot load. Returns
    (ok, message)."""
    allowed = {(t["sale"], t["reprint"]) for t in list_invoice_templates()}
    if (sale, reprint) not in allowed:
        return False, "unknown template pair: " + str(sale) + " / " + str(reprint)
    db_path = find_local_db()
    if not db_path:
        return False, "POS exe local cache not found"

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        row = conn.execute("SELECT intAccountId FROM TblSettings WHERE intID = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return False, "TblSettings row missing"
    account_id = row[0]

    # server first: if that fails, leave the cache untouched (they must agree)
    if _POS_FRAMEWORK_DIR not in sys.path:
        sys.path.insert(0, _POS_FRAMEWORK_DIR)
    import db_helpers as db
    import pyodbc
    try:
        cn = pyodbc.connect(db._conn_str(), autocommit=False)
        try:
            cur = cn.cursor()
            cur.execute("UPDATE dbo.Account SET strInvoiceName = ?, strInvoiceRePrintName = ? WHERE AccoutId = ?",
                        (sale, reprint, account_id))
            if cur.rowcount != 1:
                cn.rollback()
                return False, "server: dbo.Account row for AccoutId " + str(account_id) + " not found (" + str(cur.rowcount) + " rows)"
            cn.commit()
        finally:
            cn.close()
    except Exception as e:
        return False, "server update failed: " + str(e)[:200]

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute("UPDATE TblSettings SET strInvoiceName = ?, strInvoiceRePrintName = ? WHERE intID = 1", (sale, reprint))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return False, "server updated but exe cache failed: " + str(e)[:200]
    return True, "invoice set to " + sale + " / " + reprint + " (server account " + str(account_id) + " + exe cache)"
