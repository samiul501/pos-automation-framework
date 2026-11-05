# ============================================================
# AUDIT ENV - builds the audit's own test environment from
# nothing: suppliers -> items -> direct purchase receive, so an
# audit run never depends on whatever data happens to exist.
#
# Everything is created through the backend web UI, the way an
# operator would, and verified in the database afterwards.
#
# NAVIGATE THROUGH THE SIDEBAR, NOT BY URL (confirmed live
# 2026-09-16): opening /config/supplierProfile/create directly
# renders the form WITHOUT its "Supplier Details" section (the
# required Address field), the console logs "Feature 'Other
# Partner Profile' not found in menu list", and SAVE then does
# nothing - no request, no error. Reaching the same page through
# Configuration > Entity Master Data > Supplier Profile carries
# the menu/feature context the page needs, and the full form
# renders. The sidebar anchors sit under a sibling <ul> that
# intercepts real clicks, so they are clicked through the DOM.
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import db_helpers as db

from audit_tests import audit_web as aw

OFFICE_NAME = "Dhanmondi Outlet"
WAREHOUSE_NAME = "DISPLAY"


# ---- session / sidebar --------------------------------------------

def login_maximized(playwright, headed=True):
    """A real maximized window (no fixed viewport). The wide layout is
    what the operator sees; under headless a fixed 1920x1080 viewport
    is used instead because no_viewport collapses the sidebar there."""
    if headed:
        browser = playwright.chromium.launch(headless=False, args=["--start-maximized"])
        page = browser.new_context(no_viewport=True).new_page()
    else:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
    aw._goto(page, config.WEB_BASE_URL)
    page.fill("input[name='mobileNo']", config.WEB_MOBILE)
    page.fill("input[name='password']", config.WEB_PASSWORD)
    page.click("button:has-text('LOG IN')")
    aw._settle(page, 4)
    return browser, page


def expand_menu(page, label, pause=1.5):
    """Expand one collapsible sidebar group by its label."""
    loc = page.locator(".sbv2-label", has_text=label)
    if not loc.count():
        loc = page.locator("text=" + label)
    loc.first.click(force=True)
    time.sleep(pause)


def sidebar_goto(page, groups, href, settle=4):
    """Expand the sidebar groups in order, then click the leaf anchor
    by its href - via the DOM, since a real click is intercepted."""
    for g in groups:
        expand_menu(page, g)
    anchor = page.locator("a.sbv2-row[href='%s']" % href)
    if not anchor.count():
        raise AssertionError("sidebar anchor %s not found after expanding %s" % (href, groups))
    anchor.first.evaluate("e => e.click()")
    aw._settle(page, settle)
    if not page.url.rstrip("/").endswith(href):
        anchor.first.click(force=True)
        aw._settle(page, settle)
    return page.url


# ---- suppliers -----------------------------------------------------

def open_supplier_create(page):
    sidebar_goto(page, ["Configuration", "Entity Master Data"], "/config/supplierProfile")
    page.locator("button:has-text('Supplier')").first.click(force=True)
    aw._settle(page, 5)
    if not page.locator("input[name='shippingAddress']").count():
        raise AssertionError("supplier form rendered without its Supplier Details "
                             "section (Address) - was it opened through the sidebar?")


def create_supplier(page, name, mobile, address="Dhanmondi, Dhaka", office=OFFICE_NAME):
    """Office + Partner Name + Mobile No + Address are the mandatory
    set (confirmed live: with Address blank SAVE is a silent no-op).
    Returns the dbo.Partner row."""
    open_supplier_create(page)
    aw._pick(page, "office", office)
    page.fill("input[name='partnerName']", name)
    page.fill("input[name='mobileNo']", mobile)
    page.fill("input[name='shippingAddress']", address)
    page.locator("button:has-text('SAVE')").first.click(force=True)
    aw._settle(page, 5)
    row = find_supplier(name)
    if not row:
        raise AssertionError("supplier %r did not appear in dbo.Partner after SAVE "
                             "(url=%s, toasts=%s)" % (name, page.url, aw.toast_messages(page)))
    return row


def find_supplier(name):
    rows = db.query(
        "SELECT PartnerId, PartnerName, MobileNo, PartnerTypeId, OfficeId, IsActive "
        "FROM dbo.Partner WHERE PartnerName = ? AND PartnerTypeId = 2", [name])
    return rows[0] if rows else None


# Names a person would recognise on screen. The run tag still rides along
# so every run's data stays unique and findable, but the leading words are
# what an operator reads in a dropdown or a report.
SUPPLIER_NAMES = [
    "Meghna Food Distributors", "Padma Traders", "Jamuna Agro Supplies",
    "Surma Grocery House", "Karnaphuli Foods", "Teesta Commodities",
    "Bengal Fresh Mart", "Dhaka Wholesale Depot",
]

ITEM_NAMES = [
    "Basmati Rice 5kg", "Mustard Oil 1L", "Red Lentil 1kg", "Sugar 1kg",
    "Wheat Flour 2kg", "Green Tea 100g", "Milk Powder 500g", "Salt 1kg",
    "Turmeric Powder 200g", "Chilli Powder 200g", "Cumin Seed 100g",
    "Soybean Oil 2L", "Chickpea 1kg", "Semolina 500g", "Black Pepper 50g",
    "Coriander Powder 200g", "Vermicelli 400g", "Honey 250g",
    "Ghee 400g", "Cashew Nut 250g", "Raisin 200g", "Date Palm 500g",
    "Biscuit Pack 300g", "Instant Noodles 8pcs", "Tomato Ketchup 500g",
    "Soya Sauce 200ml", "Vinegar 500ml", "Baking Powder 100g",
]


def create_suppliers(page, count, tag):
    """`count` suppliers with readable trade names, each carrying the run
    id so the data stays identifiable: "Padma Traders (AUTO 2609...)"."""
    out = []
    for n in range(1, count + 1):
        base = SUPPLIER_NAMES[(n - 1) % len(SUPPLIER_NAMES)]
        name = "%s (AUTO %s)" % (base, tag)
        mobile = "019%s%d" % (tag[-7:], n)      # 11 digits, unique per run
        out.append(create_supplier(page, name, mobile))
    return out


# ---- items (Ant Design form, ids MGMForm_<field>) ------------------
# The item form is a different component library from the supplier
# form: Ant Design, fields addressed by id="MGMForm_<name>", selects
# whose options render in a body-level ".ant-select-dropdown". Required
# per the form's own aria-required (mapped 2026-09-16): supplier,
# barcode (unless AutoBarCode), itemName, itemType, itemCategory,
# itemSubCategory, minorCategory, uom, stdPurchasePrice (cost),
# sellingPrice, inputVatPercentage (purchase tax), vatPercentage
# (sales tax), saleSetup, itemLocation. Category -> Sub -> Minor
# cascade, so they must be picked in that order.

_ANT_OPTION = ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option"


def ant_options(page, field_id, typed=None, wait=1.2):
    """Open an Ant select and return its visible option texts. `typed`
    is for search selects (the supplier one needs >= 2 letters)."""
    page.click("#" + field_id, force=True)
    time.sleep(0.6)
    if typed:
        page.keyboard.type(typed, delay=80)
        time.sleep(max(wait, 2.2))
    else:
        time.sleep(wait)
    return [t.strip() for t in page.eval_on_selector_all(
        _ANT_OPTION, "els => els.map(e => (e.innerText || '').trim())") if t.strip()]


def ant_pick(page, field_id, text=None, typed=None, prefer=None, attempts=3):
    """Pick an option by exact text; with text=None picks `prefer` if
    present, else the first option. Returns the text picked.

    VERIFIES the selection stuck and retries (confirmed live 2026-09-19):
    an Ant select occasionally swallows the click while its option list
    is still rendering - the field stays empty, Save then does nothing at
    all (no toast, no field error) and the item silently never exists."""
    want_label = text
    for attempt in range(1, attempts + 1):
        options = ant_options(page, field_id, typed)
        if not options:
            page.keyboard.press("Escape")
            if attempt == attempts:
                raise AssertionError("no options in #%s (typed=%r)" % (field_id, typed))
            time.sleep(1.0)
            continue
        want = want_label
        if want is None:
            want = prefer if (prefer in options) else options[0]
        loc = page.locator(_ANT_OPTION, has_text=want)
        if not loc.count():
            page.keyboard.press("Escape")
            raise AssertionError("option %r not in #%s: %r" % (want, field_id, options[:10]))
        loc.first.click(force=True)
        time.sleep(0.8)
        if ant_value(page, field_id):
            return want
        if attempt == attempts:
            raise AssertionError("#%s still empty after %d attempts (wanted %r)"
                                 % (field_id, attempts, want))
        time.sleep(1.0)


def ant_value(page, field_id):
    """Text an Ant select currently shows (empty if nothing chosen).

    This build renders the chosen value as the TITLE of
    .ant-select-content (which also gains .ant-select-content-has-value),
    NOT in a .ant-select-selection-item element. Reading only the latter
    made every select look empty, which turned a perfectly good pick into
    a false "still empty" failure and broke item creation."""
    return page.evaluate(
        """id => {
            const i = document.getElementById(id);
            if (!i) return '';
            const box = i.closest('.ant-select');
            if (!box) return '';
            const item = box.querySelector('.ant-select-selection-item');
            if (item) return (item.getAttribute('title') || item.innerText || '').trim();
            const content = box.querySelector('.ant-select-content-has-value')
                         || box.querySelector('.ant-select-content');
            if (!content) return '';
            const title = content.getAttribute('title');
            if (title) return title.trim();
            const txt = (content.innerText || '').trim();
            const ph = box.querySelector('.ant-select-placeholder');
            if (ph && txt === (ph.innerText || '').trim()) return '';
            return txt;
        }""",
        field_id)


def ant_fill(page, field_id, value):
    page.fill("#" + field_id, "")
    page.fill("#" + field_id, str(value))
    time.sleep(0.2)


def open_item_create(page):
    """Open a clean Create Item form.

    Always navigates the list route first and presses Escape: after a
    save, a toast or a still-open dropdown from the previous item can sit
    over the form and swallow the next click - which showed up as an item
    that silently never saved, three retries in a row."""
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    sidebar_goto(page, ["Configuration", "Entity Master Data"], "/config/item")
    page.locator("button:has-text('Add Item')").first.click(force=True)
    aw._settle(page, 5)
    page.wait_for_selector("#MGMForm_itemName", timeout=20000)


def item_categories(page):
    o = ant_options(page, "MGMForm_itemCategory")
    page.keyboard.press("Escape")
    return o


def _create_item_once(page, supplier_name, name, cost, price, auto_barcode=False,
                barcode=None, category=None, sub_category=None, minor_category=None,
                uom=None, purchase_tax=None, sales_tax=None, sales_setup="None",
                location="All", reuse_form=False):
    """Create one item and return its dbo.Item row.

    reuse_form=True is the operator's "stay on the page" shortcut: after
    a successful save the form keeps supplier/category/uom/tax etc., so
    only name, barcode (if manual) and the two prices are changed."""
    if not reuse_form:
        ant_pick(page, "MGMForm_supplier", supplier_name, typed=supplier_name[:12])
        ant_pick(page, "MGMForm_itemType", "Finished/Trading Goods")
        chosen_cat = ant_pick(page, "MGMForm_itemCategory", category)
        chosen_sub = ant_pick(page, "MGMForm_itemSubCategory", sub_category)
        chosen_minor = ant_pick(page, "MGMForm_minorCategory", minor_category)
        ant_pick(page, "MGMForm_uom", uom, prefer="PCS")
        ant_pick(page, "MGMForm_inputVatPercentage", purchase_tax)
        ant_pick(page, "MGMForm_vatPercentage", sales_tax)
        ant_pick(page, "MGMForm_saleSetup", sales_setup)
        ant_pick(page, "MGMForm_itemLocation", location)
    else:
        chosen_cat, chosen_sub, chosen_minor = (ant_value(page, "MGMForm_itemCategory"),
                                                ant_value(page, "MGMForm_itemSubCategory"),
                                                ant_value(page, "MGMForm_minorCategory"))

    cb = page.locator("#MGMForm_isAutoBarCode")
    if cb.is_checked() != auto_barcode:
        cb.click(force=True)
        time.sleep(0.4)
    if not auto_barcode:
        ant_fill(page, "MGMForm_barcode", barcode)
    ant_fill(page, "MGMForm_itemName", name)
    ant_fill(page, "MGMForm_stdPurchasePrice", cost)
    ant_fill(page, "MGMForm_sellingPrice", price)

    page.locator("button:has-text('Save')").first.click(force=True)
    aw._settle(page, 5)

    row = find_item_wait(name)
    if not row:
        raise AssertionError("item %r not in dbo.Item after Save (url=%s, toasts=%s)"
                             % (name, page.url, aw.toast_messages(page)))
    row["_category"], row["_sub"], row["_minor"] = chosen_cat, chosen_sub, chosen_minor
    row["_form_kept"] = bool(ant_value(page, "MGMForm_supplier"))
    return row


def create_item(page, supplier_name, name, cost, price, attempts=3, **kwargs):
    """Create one item, retrying the WHOLE form if it does not appear in
    the database. A save that quietly does nothing (a dropdown that did
    not register, a click swallowed by a leftover toast) leaves no toast
    and no field error, so the database is the only reliable signal - and
    one flaky item used to abort the entire environment build. Each retry
    starts from a freshly loaded form, not the broken one."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            if attempt > 1:
                open_item_create(page)
            return _create_item_once(page, supplier_name, name, cost, price, **kwargs)
        except Exception as e:
            last = e
            print("      item %s attempt %d/%d failed: %s"
                  % (name, attempt, attempts, str(e)[:120]))
            if attempt == attempts:
                break
            time.sleep(3)
    raise last


def find_item_wait(name, timeout=20):
    """Poll dbo.Item for `name`. The save round-trip is occasionally
    slower than the page settle, and a single check right after Save
    reported "never saved" for an item that landed a second later."""
    deadline = time.time() + timeout
    while True:
        row = find_item(name)
        if row or time.time() > deadline:
            return row
        time.sleep(1.5)


def find_item(name):
    rows = db.query(
        "SELECT ItemId, ItemName, ItemCode, Barcode, SupplierId, ItemCategoryId, ItemCategoryName, "
        "ItemSubCategoryId, ItemSubCategoryName, MinorCategoryId, UomName, StdPurchasePrice, "
        "CurrentSellingPrice, AvgRate, VatPercentage, IsActive, IsAutoBarcode, BranchName "
        "FROM dbo.Item WHERE ItemName = ? ORDER BY ItemId DESC", [name])
    return rows[0] if rows else None


# ---- direct purchase receive --------------------------------------
# Purchase > Purchase Receive > "Direct Receive" (react-select form,
# container ids: office, warehouse, itemType, supplier, category,
# subCategory, minorCategory). Challan No is required. The Item box
# has no id - with "isBarcode" ticked it is the react-select whose
# placeholder reads "Search With Barcode", and that is how it is found.
# Rate and Selling Price auto-fill from the item; only VAT(%) is typed.

def open_direct_receive(page):
    sidebar_goto(page, ["Purchase"], "/purchase/goodsReceive")
    page.locator("button:has-text('Direct Receive')").first.click(force=True)
    aw._settle(page, 5)
    page.wait_for_selector("#supplier", timeout=20000)


def _item_box(page):
    return page.locator("div.css-b62m3t-container", has_text="Search With Barcode").first


def receive_add_line(page, barcode, quantity, vat_percent=5):
    """Add one line to the staged receive grid. Returns the auto-filled
    rate / selling price so a test can check they came from the item."""
    box = page.locator("div.css-b62m3t-container").filter(
        has=page.locator("[id*='placeholder']", has_text="Search With Barcode"))
    if not box.count():
        box = page.locator("input[name='isBarcode']").locator("xpath=following::div[contains(@class,'css-b62m3t-container')][1]")
    box.first.click(force=True)
    time.sleep(0.6)
    page.keyboard.type(str(barcode), delay=90)
    time.sleep(2.5)
    opt = page.locator(aw._OPTION_SELECTOR, has_text=str(barcode))
    if not opt.count():
        opt = page.locator(aw._OPTION_SELECTOR).first
    opt.first.click(force=True)
    time.sleep(1.2)

    page.fill("input[name='quantity']", str(quantity))
    rate = page.input_value("input[name='rate']")
    sell = page.input_value("input[name='sellingPrice']")
    page.fill("input[name='vat']", str(vat_percent))
    time.sleep(0.6)
    page.locator("button:has-text('Add')").last.click(force=True)
    time.sleep(1.5)
    return {"barcode": barcode, "quantity": quantity, "rate": rate, "sellingPrice": sell}


def receive_grid_rows(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
               Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim()))
               .filter(r => r.length > 3)""")


def direct_receive(page, supplier_name, lines, challan_no, office=OFFICE_NAME,
                   warehouse=WAREHOUSE_NAME, vat_percent=5):
    """One Direct Receive document for `supplier_name` with `lines` =
    [(barcode, quantity), ...]. Returns the staged grid and what the
    form auto-filled per line."""
    open_direct_receive(page)
    aw._pick(page, "office", office)
    aw._settle(page, 2)
    aw._pick(page, "warehouse", warehouse)
    aw._pick_searchable(page, "supplier", supplier_name[:14], supplier_name)
    page.fill("input[name='challanNo']", challan_no)
    added = [receive_add_line(page, bc, qty, vat_percent) for bc, qty in lines]
    grid = receive_grid_rows(page)
    if len(grid) < len(lines):
        raise AssertionError("only %d of %d lines staged: %s" % (len(grid), len(lines), grid))
    page.locator("button:has-text('SAVE')").first.click(force=True)
    aw._settle(page, 6)
    aw._confirm_modal(page, "YES")
    aw._settle(page, 3)
    return {"lines": added, "grid": grid, "url": page.url, "toasts": aw.toast_messages(page)}


def stock_at_audit_warehouse(item_ids):
    """{ItemId: CurrentStock in the audit warehouse} - the number a
    receive must move."""
    if not item_ids:
        return {}
    ph = ",".join("?" for _ in item_ids)
    rows = db.query(
        "SELECT ItemId, ISNULL(SUM(CurrentStock), 0) AS s FROM dbo.ItemWarehouseBalance "
        "WHERE WarehouseId = ? AND ItemId IN (" + ph + ") GROUP BY ItemId",
        [16] + list(item_ids))
    out = {i: 0.0 for i in item_ids}
    out.update({r["ItemId"]: float(r["s"]) for r in rows})
    return out


# ---- the whole environment -----------------------------------------
import random as _random


def cascading_categories():
    """Categories that have BOTH a sub category and a minor category,
    straight from the database.

    The item form requires all three, and most of this catalogue's 319
    categories are missing one - the old approach opened each candidate's
    dropdowns in the UI to find out, two extra round-trips per category.
    One query answers it for all 278 usable ones."""
    return db.query(
        "SELECT DISTINCT c.ItemCategoryId, c.ItemCategoryName, "
        "       s.ItemSubCategoryId, s.ItemSubCategoryName, "
        "       m.ItemMinorCategoryId, m.ItemMinorCategoryName "
        "FROM dbo.ItemCategory c "
        "JOIN dbo.ItemSubCategory  s ON s.ItemCategoryId = c.ItemCategoryId AND s.IsActive = 1 "
        "JOIN dbo.ItemMinorCategory m ON m.ItemSubCategoryId = s.ItemSubCategoryId AND m.IsActive = 1 "
        "WHERE c.IsActive = 1 AND c.AccountId = 1 "
        "ORDER BY c.ItemCategoryId DESC"
    )


def pick_categories(page, rng, count, max_tries=25):
    """`count` (category, sub, minor) triples that WORK IN THE ITEM FORM.

    Two sources, deliberately: the database narrows the candidates to the
    ~271 categories that have a sub and a minor at all (instead of trying
    all 319 blind), but the item form is the authority - it filters by
    item type/branch, so a category the database calls complete can still
    open an empty Sub Category list. Each candidate is therefore opened
    in the form and only kept once both child lists actually offer
    something."""
    db_rows = cascading_categories()
    by_cat = {}
    for r in db_rows:
        by_cat.setdefault(r["ItemCategoryName"], r)
    candidates = list(by_cat.keys())
    rng.shuffle(candidates)

    open_item_create(page)
    offered = set(item_categories(page))
    candidates = [c for c in candidates if c in offered]

    chosen, tried = [], 0
    for cat in candidates:
        if len(chosen) >= count or tried >= max_tries:
            break
        tried += 1
        try:
            ant_pick(page, "MGMForm_itemCategory", cat)
            subs = ant_options(page, "MGMForm_itemSubCategory")
            page.keyboard.press("Escape")
            if not subs:
                continue
            ant_pick(page, "MGMForm_itemSubCategory", subs[0])
            minors = ant_options(page, "MGMForm_minorCategory")
            page.keyboard.press("Escape")
            if not minors:
                continue
            chosen.append({"category": cat, "sub": subs[0], "minor": minors[0]})
        except Exception:
            continue
    if len(chosen) < count:
        raise AssertionError("only %d of %d usable categories found in the item form "
                             "after %d tries" % (len(chosen), count, tried))
    return chosen


def build_environment(page, seed=None, suppliers=None, items_per_supplier=None,
                      categories=2, log=print, existing_tag=None):
    """Suppliers -> items -> direct receive, all random within the
    operator's ranges (3-5 suppliers, 8-10 items each). Every supplier
    gets items in EVERY chosen category, so each category is shared by
    all suppliers - the shape the supplier-scope test needs.

    Returns everything created, with DB ids, for the audit to use."""
    rng = _random.Random(seed)
    tag = time.strftime("%y%m%d%H%M%S")
    n_sup = suppliers or rng.randint(3, 5)
    n_items = items_per_supplier or rng.randint(8, 10)
    log("env: tag=%s suppliers=%d items/supplier=%d" % (tag, n_sup, n_items))

    if existing_tag:
        # Resume a build whose suppliers already exist (item profile onward).
        tag = existing_tag
        sups = db.query(
            "SELECT PartnerId, PartnerName, MobileNo, PartnerTypeId, OfficeId, IsActive "
            "FROM dbo.Partner WHERE PartnerName LIKE ? AND PartnerTypeId = 2 ORDER BY PartnerId",
            ["%%(AUTO %s)%%" % existing_tag])
        if not sups:
            raise AssertionError("no suppliers with tag %s to resume from" % existing_tag)
        log("env: resuming with %d existing suppliers (tag %s)" % (len(sups), tag))
    else:
        sups = create_suppliers(page, n_sup, tag)
    log("env: suppliers -> %s" % [(s["PartnerId"], s["PartnerName"]) for s in sups])

    cats = pick_categories(page, rng, categories)
    log("env: categories -> %s" % cats)

    items = []
    k = 0
    for s in sups:
        for n in range(1, n_items + 1):
            k += 1
            cat = cats[(n - 1) % len(cats)]
            cost = rng.randint(50, 500)
            price = round(cost * rng.uniform(1.2, 1.6))
            auto = rng.random() < 0.5
            name = "%s (AUTO %s-%d)" % (ITEM_NAMES[(k - 1) % len(ITEM_NAMES)], tag, k)
            open_item_create(page)
            row = create_item(page, s["PartnerName"], name, cost, price,
                              auto_barcode=auto, barcode=None if auto else "A%s%03d" % (tag[-6:], k),
                              category=cat["category"], sub_category=cat["sub"],
                              minor_category=cat["minor"])
            row["_supplier"] = s["PartnerName"]
            items.append(row)
            log("env: item %2d %-28s %-12s cost=%s price=%s cat=%s" %
                (k, name, row["Barcode"], cost, price, cat["category"]))

    receives = []
    for s in sups:
        mine = [i for i in items if i["SupplierId"] == s["PartnerId"]]
        lines = [(i["Barcode"], rng.randint(3, 20)) for i in mine]
        r = direct_receive(page, s["PartnerName"], lines, challan_no="AUTO-CH-%s-%d" % (tag, s["PartnerId"]))
        receives.append({"supplier": s["PartnerName"], "lines": lines, "toasts": r["toasts"]})
        log("env: received %d lines for %s -> %s" % (len(lines), s["PartnerName"], r["toasts"][:1]))

    stock = stock_at_audit_warehouse([i["ItemId"] for i in items])
    for i in items:
        i["_stock"] = stock.get(i["ItemId"], 0.0)
    return {"tag": tag, "seed": seed, "suppliers": sups, "categories": cats,
            "items": items, "receives": receives}


def load_environment(tag):
    """Rebuild the environment dict for a run that already created its
    suppliers/items (named AUTO-SUP-<tag>-n / AUTO-ITEM-<tag>-n), so an
    audit can be re-run on it without creating everything again."""
    sups = db.query(
        "SELECT PartnerId, PartnerName, MobileNo, PartnerTypeId, OfficeId, IsActive "
        "FROM dbo.Partner WHERE PartnerName LIKE ? AND PartnerTypeId = 2 ORDER BY PartnerId",
        ["%%(AUTO %s)%%" % tag])
    items = db.query(
        "SELECT ItemId, ItemName, ItemCode, Barcode, SupplierId, ItemCategoryId, ItemCategoryName, "
        "ItemSubCategoryId, ItemSubCategoryName, MinorCategoryId, UomName, StdPurchasePrice, "
        "CurrentSellingPrice, AvgRate, VatPercentage, IsActive, IsAutoBarcode "
        "FROM dbo.Item WHERE ItemName LIKE ? ORDER BY ItemId", ["%%(AUTO %s-%%" % tag])
    if not sups or not items:
        raise AssertionError("no environment with tag %s in the database" % tag)
    stock = stock_at_audit_warehouse([i["ItemId"] for i in items])
    names = {s["PartnerId"]: s["PartnerName"] for s in sups}
    for i in items:
        i["_stock"] = stock.get(i["ItemId"], 0.0)
        i["_supplier"] = names.get(i["SupplierId"])
    cats = sorted({(i["ItemCategoryId"], i["ItemCategoryName"], i["ItemSubCategoryId"], i["ItemSubCategoryName"]) for i in items})
    return {"tag": tag, "seed": None, "suppliers": sups,
            "categories": [{"category": c[1], "sub": c[3], "category_id": c[0], "sub_id": c[2]} for c in cats],
            "items": items, "receives": []}
