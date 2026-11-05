# ============================================================
# Test data for Purchase Order create.
#
# Local PO references master data that must ALREADY exist in the
# environment - it does not create anything named - so unlike the
# item/employee builders this needs no per-run uniqueness.
#
# The supplier and item pickers are react-selects with no way to
# select by code, so each profile has to supply a `search` string
# to type and an `option` pattern to match. `code` is the stable
# identifier the line-item row assertion looks for.
# ============================================================


def get_local_purchase_order_data(profile):
    """One Local Purchase Order create run's worth of data."""
    # master["item"] is what the Item CREATE form needs; the PO pickers
    # need an item that already exists, which is a different record and so
    # a different key.
    supplier = profile.data("supplier")
    item = profile.data("item_lookup")

    return {
        "office": profile.data("office"),
        "supplierSearch": supplier["search"],
        "supplierOption": supplier["option"],
        "itemSearch": item["search"],
        "itemOption": item["option"],
        "itemCode": item["code"],
        # Plain transaction inputs, not master data - literals are fine.
        "quantity": 10,
        "rate": 50,
    }
