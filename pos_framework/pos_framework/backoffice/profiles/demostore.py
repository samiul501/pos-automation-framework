# ============================================================
# DemoStore - demo-backoffice.example.com, backed by the DemoStore
# database. This is the environment the exe suites already drive,
# so the two halves of the framework meet on the same data.
#
# Everything below was read off the live app during earlier work,
# not assumed:
#   * Configuration has NO "Entity Master Data" level - the master
#     screens hang straight off it
#   * the create button on Customer Profile is labelled "Customer",
#     not "Add Customer"
#   * reaching /config/custoemerProfile/create BY URL renders the
#     form without Credit Limit, Credit Days, Territory or Customer
#     Point - they are permission-gated and only load when the page
#     is reached through the menu, hence menu_only_form_gating
#   * the account has auto item code switched on: a bulk upload or
#     create that supplies its own ItemCode is rejected with
#     "Auto itemcode is active for this account"
# ============================================================

from backoffice.profiles.base import Profile


class DemoStore(Profile):
    key = "demostore"
    label = "DemoStore"

    base_url = "https://demo-backoffice.example.com/"
    username_env = "WEB_MOBILE"        # already in .env, shared with the exe suites
    password_env = "WEB_PASSWORD"
    database = "DemoStore"

    nav = {
        "item_create": ["Configuration", "Item Profile"],
        "customer_create": ["Configuration", "Customer Profile"],
        "supplier_create": ["Configuration", "Supplier Profile"],
        "employee_create": ["Configuration", "Employee"],
        "purchase_receive": ["Purchase", "Purchase Receive"],
        "purchase_order": ["Purchase", "Purchase Order"],
        "sales_delivery": ["Sales", "Sales Delivery"],
        "pos_reports": ["POS", "Reports"],
    }

    buttons = {
        "item_create": "Add Item",
        "customer_create": "Customer",          # not "Add Customer"
        "supplier_create": "Supplier",
        "purchase_receive": "Direct Receive",
        "purchase_order": "Create Local Order",
    }

    # NOT mapped here yet, on purpose - the tests for them skip and say so:
    #
    #   purchase_order   the form exists and opens, but its Item picker
    #                    returns nothing for any search until the item is
    #                    purchasable under the chosen category chain; the
    #                    right reference item still has to be chosen
    #   employee_create  "Employee" under Configuration does not open an
    #                    employee list on this account
    #   other_partner_create / language_configuration
    #                    these screens do not exist in this app at all

    # How this app builds each form. Read off the live app, not assumed -
    # Item create here is a react-select/Formik page whose controls are
    # found by wrapper id, nothing like StoreB's Ant Design version.
    forms = {
        "item_create": {
            "save": "SAVE",
            "fields": [
                # Supplier only loads options once you type, and every
                # option is prefixed with the supplier's id ("1 - 313
                # Naogaon Distribution (...)"), so the search string and
                # the option text are both given by master["item"].
                {"kind": "search_select", "target": "supplier", "value": "supplier",
                 "query": "313"},
                {"kind": "text", "target": "barcode", "value": "barcode"},
                {"kind": "text", "target": "itemName", "value": "masterItemName"},
                {"kind": "select", "target": "itemType", "value": "itemType"},
                # Category -> Sub -> Minor is a cascade: Sub has no options
                # until a Category is chosen, Minor none until a Sub is.
                # They must be filled in this order.
                {"kind": "select", "target": "itemCategory", "value": "category"},
                {"kind": "select", "target": "itemSubCategory", "value": "subCategory"},
                {"kind": "select", "target": "minorCategory", "value": "minorCategory"},
                {"kind": "select", "target": "uom", "value": "uom"},
                # A redeploy on 30 Sep 2026 folded half of this form behind a
                # "View Details" toggle (BasePage.expand_sections opens it) and
                # removed three fields outright: inputVatPercentage, saleSetup
                # and locationGroup. Only the output VAT setup remains.
                {"kind": "select", "target": "vatPercentage", "value": "outputTax"},
                # Location was gated by Location Group, which the 30 Sep
                # redeploy removed - so it now offers nothing and is left
                # alone. Marked optional in case a later build brings the
                # pair back.
                {"kind": "select", "target": "itemLocation", "value": "itemLocation",
                 "optional": True},
                {"kind": "text", "target": "sellingPrice", "value": "sellingPrice"},
            ],
        },

        # Customer create. Every name below is the one the credit-sales
        # suite already drives successfully against this app - creditLimit
        # and paymentDays included, which are the two fields that vanish
        # if the form is reached by URL instead of through the menu.
        "customer_create": {
            "save": "SAVE",
            "fields": [
                {"kind": "select", "target": "office", "value": "office"},
                {"kind": "text", "target": "partnerName", "value": "partnerName"},
                {"kind": "text", "target": "partnerBillingName",
                 "value": "partnerBillingName"},
                {"kind": "text", "target": "mobileNo", "value": "mobile"},
                {"kind": "text", "target": "paymentDays", "value": "creditDays"},
                {"kind": "text", "target": "creditLimit", "value": "creditLimit"},
                {"kind": "select", "target": "territory", "value": "territory"},
                # Customer Point is required here and does not exist on StoreB.
                {"kind": "select", "target": "customerPoint", "value": "customerPoint"},
            ],
        },

        "supplier_create": {
            "save": "SAVE",
            "fields": [
                {"kind": "select", "target": "office", "value": "office"},
                {"kind": "text", "target": "partnerName", "value": "partnerName"},
                {"kind": "text", "target": "mobileNo", "value": "mobile"},
            ],
        },
    }

    master = {
        "office": "Dhanmondi Outlet",
        "warehouse": "DISPLAY",
        "branch": "Demo Super Shop",
        "customer": {
            "territory": "ORG-AGORA - Agora Limited",
            "customerPoint": "Membership-1 x 2",
            # Defaults for a plain customer. The credit-sales suite varies
            # these per run; a create test only needs them to be valid.
            "creditLimit": 5000,
            "creditDays": 10,
        },
        # Reference data the Purchase Receive (GRN) screen needs. The
        # supplier is searched by NAME here, but the ITEM is searched by
        # its code/barcode - and only once a supplier is chosen.
        "receive": {
            "supplier": "1 - 313 Naogaon Distribution (01700000002)",
            "supplier_query": "Naogaon",
            # dbo.Partner.PartnerId for that supplier - the receive item
            # picker only offers items belonging to it, so a multi-item
            # test has to draw its items from the same place.
            "supplier_id": 1,
            "warehouse": "DISPLAY",
            "payment_method": "Cash",
        },
        # Reference data the Item form needs, all of it confirmed present
        # on dev. Orange-1 / orange-2 / orange-3 is the one category chain
        # on this account that goes all three levels deep, which the form
        # requires - most categories have no sub category at all.
        "item": {
            "supplier": "1 - 313 Naogaon Distribution (01700000002)",
            "itemType": "Finished/Trading Goods",
            "category": "Orange-1",
            "subCategory": "orange-2",
            "minorCategory": "orange-3",
            "uom": "PCS",
            "inputTax": "VAT-[15.00%]",
            "outputTax": "VAT-[15.00%]",
            # "None" = no special sale handling. The other two choices
            # (Allow Negative Stock, Allow Multiple Sale Price) change how
            # the item behaves at the till, so a plain item takes None.
            "saleSetup": "None",
            "locationGroup": "Parlour",
            "itemLocation": "Dhanmondi",
        },
    }

    flags = {
        "auto_item_code": True,
        "menu_only_form_gating": True,
        # StoreB rejects a partner whose address was typed but never pushed
        # into the list with "Add List". This app saves without one, so
        # the step is skipped rather than failing on a button that is
        # there but not required.
        "address_list_required": False,
    }
