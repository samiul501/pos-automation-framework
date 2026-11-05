# ============================================================
# PURCHASE RECEIVE (Direct Receive) - the GRN screen.
#
# Written for the client issue "GRN amount changes when it is
# saved", so its job is not only to fill the form but to READ the
# money off it, before and after the save, exactly as a person
# comparing the invoice with the saved GRN would.
#
# WHAT THIS SCREEN TAUGHT US (all confirmed live on dev)
#
#   * the item picker searches by ITEM CODE / BARCODE, never by
#     name - "Rice" finds nothing, "2033791870374" finds it
#   * and only AFTER a supplier is chosen; before that it is
#     empty for every search
#   * Challan No was required; without it SAVE did nothing at
#     all - no toast, no error, the page just sat there
#   * the screen was redesigned on 29 Sep 2026: Payment Method and
#     Selling Price are gone, "Item Total"/"Purchase Total" became a
#     single "Total Amount", and Supplier now starts on "Anonymous"
#   * "Price Including VAT" defaults to ON, which extracts VAT
#     out of the rate. The client's invoice adds VAT on top, so
#     reproducing their case means turning it OFF
#   * the Rate field accepts only 2 decimals: typing 29.985
#     leaves 29.98 behind. That matters here - see the test
# ============================================================

import re

from backoffice.pages.base_page import BasePage

# The summary block, in the order the screen shows it. Read by label
# because the block has no ids of its own - and the labels are the same
# words the client uses, which keeps the report readable.
TOTAL_LABELS = [
    "Total Qty",
    "Item Total",
    "Total VAT",
    "Item Total(with VAT)",
    "Discount",
    "Labour Charge",
    "Delivery Charge",
    "Other Charges",
    "Pending Amount",
    "Purchase Total",
    "Average Margin",
]


def to_number(text):
    """'45,872.14' -> 45872.14 ; '' or junk -> None."""
    if text is None:
        return None
    cleaned = str(text).replace(",", "").replace("%", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


class PurchaseReceivePage(BasePage):
    """Direct Receive: header, one or more lines, the totals block, save."""

    SCREEN = "purchase_receive"

    # ---- getting there ----------------------------------------------

    def open_form(self):
        self.open_create(self.SCREEN)
        self.page.wait_for_selector("input[name='challanNo']", timeout=45000)
        self.page.wait_for_timeout(self.SETTLE_MS)
        return self

    # ---- header ------------------------------------------------------

    def set_price_including_vat(self, on):
        """ON extracts VAT out of the rate; OFF adds it on top.

        The client's invoice adds it on top, and the default here is ON,
        so a faithful reproduction has to say which it wants.
        """
        box = self.page.locator("input[name='isPriceIncludingVat']")
        if not box.count():
            return self
        if box.is_checked() != bool(on):
            box.set_checked(bool(on), force=True)
            self.page.wait_for_timeout(1200)
        return self

    def fill_header(self, office, warehouse, supplier, challan_no,
                    payment_method="Cash", supplier_query=None):
        """Office, warehouse, supplier and challan.

        Payment Method is filled only when the screen still has it. A
        redeploy on 29 Sep 2026 removed that control from Direct Receive
        (replacing it with "Payment Days after Receive"), and a test that
        insists on a field the product no longer shows is reporting its
        own staleness, not a defect.
        """
        self.select_option("office", office)
        self.select_option("warehouse", warehouse)
        if self.page.locator("#paymentMethod").count():
            self.select_option("paymentMethod", payment_method)

        # Supplier is searched by NAME (unlike the item picker below), and
        # since that redeploy it starts on "Anonymous" rather than empty -
        # so it must be set, not merely left alone.
        self.search_option("supplier", supplier_query or supplier.split("-")[-1].strip()[:8],
                           supplier)
        self.fill("challanNo", challan_no)
        self.page.wait_for_timeout(800)
        return self

    # ---- one line ----------------------------------------------------

    def add_line(self, item_code, quantity, rate, selling_price, vat_percent=None,
                 item_name=None):
        """Fill one line and press Add.

        `item_code` is what the picker SEARCHES on - a barcode or an
        item code; it does not search by name. But since the 30 Sep
        redeploy the option it returns is labelled with the app's own
        auto item code ("FG-01434 - Potato_8223(PCS)"), which is not the
        barcode that was typed. So the match is made on `item_name` when
        one is given, and only falls back to the code.

        Returns what the line showed BEFORE it was added, which is worth
        capturing - it is the first place the arithmetic can drift.
        """
        page = self.page
        self.search_option("item", str(item_code), str(item_name or item_code))

        self.fill("quantity", quantity)
        page.wait_for_timeout(400)
        self.fill("rate", rate)
        page.wait_for_timeout(600)
        if self.has_field("sellingPrice"):
            self.fill("sellingPrice", selling_price)
        page.wait_for_timeout(500)
        if vat_percent is not None and self.has_field("vat"):
            self.fill("vat", vat_percent)
        page.wait_for_timeout(900)

        typed = {
            "rate_typed": str(rate),
            "rate_field": self.value_of("rate"),
            "quantity": self.value_of("quantity"),
            "vat": self.value_of("vat"),
            "vat_amount": self.value_of("vatAmount"),
            "item_total": self.value_of("totalAmount"),
            "purchase_total": self.value_of("purchaseTotal"),
        }

        page.get_by_role("button", name="Add", exact=True).first.click(force=True)
        page.wait_for_timeout(2500)
        return typed

    def line_rows(self):
        """Every added line as the grid shows it - the per-line numbers a
        reader needs when the totals disagree."""
        return self.page.evaluate("""() => {
            const rows = [];
            document.querySelectorAll('table tbody tr').forEach(tr => {
                const cells = [...tr.querySelectorAll('td')].map(td => {
                    const input = td.querySelector('input');
                    return (input ? input.value : (td.innerText || '')).trim();
                });
                if (cells.length > 4) rows.push(cells);
            });
            return rows;
        }""")

    # ---- discount and the totals block --------------------------------

    def set_discount_percent(self, percent):
        box = self.page.locator("input[placeholder='%']").first
        if not box.count():
            raise AssertionError("no discount % field on this screen")
        box.click()
        box.fill(str(percent))
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(1800)
        return self

    def set_charges(self, labour=None, delivery=None, other=None):
        """Labour / Delivery / Other charges on the summary block.

        These are the numerators the procedure divides by the item total
        to spread a cost across the lines, so they are the fields most
        likely to make that division explode.

        They have no name attribute - only a placeholder - so that is
        what they are found by.
        """
        for placeholder, value in (("Labour Charge", labour),
                                   ("Delivery Charge", delivery),
                                   ("Other Charges", other)):
            if value is None:
                continue
            box = self.page.get_by_placeholder(placeholder).first
            if not box.count():
                continue
            box.click()
            box.fill(str(value))
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(1200)
        return self

    def error_text(self):
        """Whatever the app is complaining about - toast, inline error or
        a server message rendered into the page."""
        found = self.page.evaluate("""() => {
            const out = [];
            document.querySelectorAll(
                '.Toastify__toast-body, [class*="toast"], [role="alert"],'
                + ' [class*="error"], .invalid-feedback, .text-danger'
            ).forEach(e => {
                const t = (e.innerText || '').trim();
                if (t) out.push(t);
            });
            return out;
        }""")
        return [t for t in dict.fromkeys(found) if t]

    def totals(self):
        """The summary block as {label: number}.

        Three things this has to get right, each of which cost an
        attempt:

        1. SCOPE. "Item Total" is also a field label above the grid and
           a column header inside it. Searching the whole page finds the
           empty one and reports 0. So the summary card is located first
           - by "Average Margin", which appears nowhere else - and only
           it is read.
        2. INPUTS. Discount is not text; it lives in two inputs (% and
           Taka). Their values have to be gathered or the row reads
           empty.
        3. THE ROW. The label and the value are siblings, so the text to
           parse is the label's PARENT.
        """
        # raw string: the JS regex below contains backslashes
        return self.page.evaluate(
            r"""(labels) => {
            const all = [...document.querySelectorAll('div,span,p,b,strong,td,li')];

            // The summary card: the SMALLEST box that holds both of these.
            // It used to be found from "Average Margin", but the 30 Sep
            // redeploy dropped that row, and anchoring on a line that may
            // vanish makes the whole block unreadable. These two have been
            // on the card in every version so far.
            let box = null;
            all.forEach(e => {
                const t = e.innerText || '';
                if (!/Total Qty/.test(t) || !/Purchase Total/.test(t)) return;
                if (!box || (e.innerText || '').length < (box.innerText || '').length) box = e;
            });
            if (!box) return {};

            const inside = [...box.querySelectorAll('div,span,p,b,strong,td,li')];
            const out = {};
            labels.forEach(label => {
                const tag = inside.find(e => {
                    const t = (e.innerText || '').trim();
                    return t === label + ' :' || t === label + ':' || t === label;
                });
                if (!tag) return;
                const row = tag.parentElement || tag;
                let text = (row.innerText || '').split(label).join(' ');
                row.querySelectorAll('input').forEach(i => {
                    if (i.value !== '' && i.value != null) text += ' ' + i.value;
                });
                const numbers = text.match(/-?[\d,]+\.?\d*/g) || [];
                if (numbers.length) {
                    out[label] = parseFloat(numbers[numbers.length - 1].replace(/,/g, ''));
                }
            });
            return out;
        }""", TOTAL_LABELS)

    # ---- saving --------------------------------------------------------

    def save_receive(self):
        self.page.get_by_role("button", name="SAVE", exact=False).first.click(force=True)
        self.page.wait_for_timeout(4000)
        return self

    def saved(self):
        """Did the save actually go through?

        Leaving the create page is the reliable signal here: this screen
        does not always raise a toast, and a missing required field makes
        SAVE do nothing at all rather than complain.
        """
        return "/create" not in self.page.url

    def grn_number(self):
        """The GRN reference the app shows after saving, if any."""
        found = re.findall(r"GRN-[A-Z0-9-]+", self.page.inner_text("body"))
        return found[0] if found else None

    # ---- the saved GRN, seen the three ways a user sees it -----------
    #
    # The client's complaint is that these disagree with the create
    # screen, so each one is read rather than assumed. There is no Edit
    # for a received GRN on this app - the row offers View, two prints
    # and a barcode, nothing else.

    LABELS_ON_SAVED = [
        "Total Qty", "Item Price", "Item Total(with VAT)", "Item Total",
        "Total VAT", "VDS Amount", "Total Discount", "Discount",
        "Total Price", "Purchase Total", "Pending Amount",
    ]

    def _amounts_in_text(self, text):
        import re as _re
        pattern = _re.compile(
            r"(" + "|".join(_re.escape(l) for l in self.LABELS_ON_SAVED) + r")"
            r"\s*:?\s*\|?\s*([\d,]+\.\d{2}|[\d,]+)", _re.IGNORECASE)
        found = {}
        for label, value in pattern.findall(text):
            found.setdefault(label.strip(), to_number(value))
        return found

    def open_saved_view(self, grn_code):
        """The "Received SPO Details" page for a saved GRN.

        Reached through the list like a person reaches it: this app
        renders a DIFFERENT page when a screen is opened by URL, so the
        row is found on the RECEIVED PO tab and its View action clicked.
        The id is still used - to pick the right row.
        """
        self.open_received_list()
        row = self.page.locator("table tbody tr", has_text=str(grn_code or "")).first
        if not row.count():
            raise AssertionError("no row for %s on the RECEIVED PO tab" % grn_code)
        row.locator("button, a").first.click(force=True)
        self.page.wait_for_timeout(5000)
        return self._amounts_in_text(self.page.inner_text("body"))

    def open_received_list(self):
        """The list, on the RECEIVED PO tab where saved GRNs live.

        The tabs are MUI tabs - role "tab", not "button" - and the list
        opens on APPROVED PO, which holds orders awaiting receive and
        not a single saved GRN.
        """
        self.open("purchase_receive")
        self.page.wait_for_timeout(2000)
        tab = self.page.get_by_role("tab", name="RECEIVED PO").first
        tab.wait_for(state="visible", timeout=45000)
        tab.click(force=True)
        self.page.wait_for_selector("table tbody tr", timeout=45000)
        self.page.wait_for_timeout(2000)
        return self

    def open_printed_grn(self, grn_code):
        """The printed GRN for that row - the document an outlet compares
        against the supplier's invoice.

        The row's action icons carry no title, label or distinct class;
        they are told apart only by order. Index 3 is the GRN print,
        which is why the caller is handed the URL to check rather than
        being asked to trust the click.
        """
        row = self.page.locator("table tbody tr", has_text=grn_code).first
        if not row.count():
            raise AssertionError("no row for %s on the RECEIVED PO tab" % grn_code)
        buttons = row.locator("button, a")
        if buttons.count() < 4:
            raise AssertionError("that row has only %d actions" % buttons.count())
        buttons.nth(3).click(force=True)
        self.page.wait_for_timeout(6000)
        return self.page.url, self._amounts_in_text(self.page.inner_text("body"))
