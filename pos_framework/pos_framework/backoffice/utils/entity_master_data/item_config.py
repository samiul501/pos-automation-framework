# ============================================================
# Test data for Item create.
#
# Converted from the source suite: same name pool, same shape.
# Two changes, both because the suite now serves two apps.
#
# 1. It generates every field EITHER app might ask for - a
#    barcode and a price as well as a code and a name. The form
#    recipe in the profile decides which of them get typed, so
#    one dict works on both and the test reads the same either
#    way.
#
# 2. Whatever the environment lists under master["item"] is
#    merged in under its own key, so a profile can feed its
#    recipe (category, tax setup, UOM...) without this file
#    needing to know those screens exist.
# ============================================================

from backoffice.utils import randoms

ITEM_NAMES = [
    "Rice", "Wheat Flour", "Sugar", "Lentils", "Cooking Oil",
    "Salt", "Onion", "Garlic", "Potato", "Chickpeas",
]


def generate_item_data(profile):
    """One Item create run's worth of data."""
    data = {
        "masterItemCode": "ITM-" + randoms.digits(5),
        "masterItemName": randoms.unique_name(ITEM_NAMES),
        # A barcode has to be unique or the save is rejected as a
        # duplicate. 13 digits with a fixed "20" prefix keeps these
        # identifiable as test data and out of the range of the "99"
        # weighing-scale barcodes the exe suites care about.
        "barcode": "20" + randoms.digits(11),
        "sellingPrice": 100,
        "costPrice": 80,
    }
    # The environment's own reference values win, and add any extra keys
    # its form recipe names (category, subCategory, inputTax, ...).
    data.update(profile.data("item", default={}))
    return data
