# ============================================================
# StoreB - storeb-backoffice.example.com, backed by the SME database.
#
# Nav trails and master data were taken from the existing
# posapp-qa-automation suite, which was written against this
# environment; anything not yet exercised there is left out
# rather than guessed, so a missing key fails loudly instead of
# clicking the wrong menu.
# ============================================================

from backoffice.profiles.base import Profile


class StoreB(Profile):
    key = "storeb"
    label = "StoreB"

    base_url = "https://storeb-backoffice.example.com/"
    username_env = "MGM_USERNAME"
    password_env = "MGM_PASSWORD"
    database = "SME"

    # StoreB groups the master-data screens under an extra "Entity Master
    # Data" level that DemoStore does not have.
    nav = {
        "item_create": ["Configuration", "Entity Master Data", "Item Profile"],
        "customer_create": ["Configuration", "Entity Master Data", "Customer Profile"],
        "supplier_create": ["Configuration", "Entity Master Data", "Supplier Profile"],
        "employee_create": ["Configuration", "Entity Master Data", "Employee"],
        "other_partner_create": ["Configuration", "Entity Master Data",
                                 "Other Partner Profile"],
        "language_configuration": ["Configuration", "Business Config",
                                   "Language Configuration"],
        "purchase_order": ["Purchase", "Purchase Order"],
        "sales_delivery": ["Sales", "Sales Delivery"],
    }

    buttons = {
        "item_create": "Add Item",
        "customer_create": "Add Customer",
        "supplier_create": "Add Supplier",
        "employee_create": "Employee Create",
        # The list header button reads "+ Supplier & Customer"; the "+" is
        # an icon inside the accessible name, so the match is loose.
        "other_partner_create": "Supplier & Customer",
        "purchase_order": "Create Local Order",
    }

    # StoreB's Item create is an Ant Design form: its controls carry real
    # accessible names, including the label's trailing affordance text
    # ("* UOM See All plus") - dropping that stops the locator matching.
    # It asks for none of the supplier/barcode/category chain DemoStore
    # demands, which is why the form shape lives here and not in the page
    # object.
    forms = {
        "item_create": {
            "save": "Save",
            "fields": [
                {"kind": "antd_text", "target": "* Master Item code",
                 "value": "masterItemCode", "skip_if_flag": "auto_item_code"},
                {"kind": "antd_text", "target": "* Master Item name",
                 "value": "masterItemName"},
                {"kind": "antd_select", "target": "* UOM See All plus", "value": "uom"},
            ],
        },

        # Customer / Other Partner: react-select widgets targeted by their
        # wrapper id (their inputs have no accessible name - the id is
        # duplicated across every select on the page, which breaks label
        # association), plus plain Ant Design textboxes.
        "customer_create": {
            "save": "SAVE",
            "fields": [
                {"kind": "select", "target": "office", "value": "office"},
                {"kind": "antd_text", "target": "Partner Name", "value": "partnerName"},
                {"kind": "antd_text", "target": "Partner Billing Name",
                 "value": "partnerBillingName"},
                {"kind": "antd_text", "target": "Mobile No", "value": "mobile"},
                {"kind": "select", "target": "territory", "value": "territory"},
            ],
        },

        # Supplier's selects go through the sticky kind: this form
        # re-renders in the background after its master data loads and has
        # been seen to discard a selection that Playwright watched succeed.
        "supplier_create": {
            "save": "SAVE",
            "fields": [
                {"kind": "sticky_select", "target": "office", "value": "office"},
                {"kind": "antd_text", "target": "Partner Name", "value": "partnerName"},
                {"kind": "antd_text", "target": "Mobile No", "value": "mobile"},
            ],
        },

        "other_partner_create": {
            "save": "SAVE",
            "fields": [
                {"kind": "sticky_select", "target": "office", "value": "office"},
                {"kind": "antd_text", "target": "Partner Name", "value": "partnerName"},
                {"kind": "antd_text", "target": "Partner Billing Name",
                 "value": "partnerBillingName"},
                {"kind": "antd_text", "target": "Mobile No", "value": "mobile"},
                {"kind": "sticky_select", "target": "territory", "value": "territory"},
            ],
        },

        "employee_create": {
            "save": "Save",
            "fields": [
                {"kind": "antd_text", "target": "Employee Id", "value": "employeeId"},
                {"kind": "antd_text", "target": "* Name", "value": "name"},
                {"kind": "antd_select", "target": "* Designation ADD NEW",
                 "value": "designation"},
                {"kind": "antd_text", "target": "* Mobile No", "value": "mobile"},
                {"kind": "antd_select", "target": "* Employee Type", "value": "employeeType"},
                {"kind": "antd_select", "target": "* Office", "value": "office"},
                {"kind": "antd_text", "target": "* NID/ Citizen / Civil / NIN / IDNumber",
                 "value": "nid"},
                # Supervisor / Line Manager fetch their options only once
                # something is typed.
                {"kind": "antd_search_select", "target": "* Supervisor", "value": "supervisor"},
                {"kind": "antd_search_select", "target": "* Line Manager",
                 "value": "lineManager"},
            ],
        },

        # Local Purchase Order. This screen has no aria wiring at all, so
        # its controls are reached through the markup around them: Office
        # by the hidden input that carries its name, Supplier and Item by
        # the placeholder text they show.
        "purchase_order": {
            "save": "SAVE",
            "fields": [
                {"kind": "named_select", "target": "office", "value": "office"},
                {"kind": "placeholder_select",
                 "target": "Select/Search Supplier (min 3 letters)",
                 "value": "supplierOption", "query_value": "supplierSearch"},
                {"kind": "placeholder_select",
                 "target": "Select/Search Item (min 3 letters)",
                 "value": "itemOption", "query_value": "itemSearch"},
                {"kind": "placeholder_text", "target": "Qty", "value": "quantity"},
                {"kind": "placeholder_text", "target": "Rate", "value": "rate"},
            ],
        },

        # The permission row inside Employee create. Its "Office" is a
        # second, distinct combobox from Personal Info's "* Office", hence
        # the exact match.
        "employee_user_account": {
            "fields": [
                {"kind": "antd_select", "target": "Business Unit", "value": "businessUnit"},
                {"kind": "antd_select", "target": "Office", "value": "office", "exact": True},
                {"kind": "antd_select", "target": "Warehouse", "value": "warehouse"},
            ],
        },
    }

    master = {
        "office": "StoreB Head Office",
        "customer": {"territory": "Vuapur (Dakuri)"},
        "employee": {
            "businessUnit": "POS App",
            "warehouse": "StoreB Warehouse Two",
            "supervisor": "POS App Development",
            "lineManager": "POS App Development",
        },
        "item": {"uom": "PCS"},
        "language": {"target": "Bangla"},
        # The Purchase Order pickers cannot select by code, so each needs a
        # string to type and the option text that comes back. Taken from the
        # source suite's test_data/dev/master_data.py, which was written
        # against this same environment.
        "supplier": {
            "code": "258",
            "search": "Agora",
            "option": "258 - Agora LTD (01700000001)",
        },
        "item_lookup": {
            "code": "AAAAaaa",
            "search": "Rice",
            "option": "AAAAaaa - Rice 1kg(PCS)",
        },
    }

    flags = {
        "auto_item_code": False,
        "menu_only_form_gating": False,
    }
