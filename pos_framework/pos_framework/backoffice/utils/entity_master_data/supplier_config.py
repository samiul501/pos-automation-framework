# ============================================================
# Test data for Supplier create. Converted from the source suite;
# office now comes from the profile instead of StoreB's master_data.
# ============================================================

from backoffice.utils import randoms

SUPPLIER_NAMES = [
    "Bengal Traders", "Padma Enterprise", "Meghna Distribution", "Sonar Bangla Store",
    "Jamuna Mart", "Karnaphuli & Sons", "Surma Retail", "Titas Enterprise",
    "Brahmaputra Trading", "Buriganga Wholesale",
]


def generate_supplier_data(profile):
    """One Supplier create run's worth of data."""
    return {
        "office": profile.data("office"),
        "partnerName": randoms.unique_name(SUPPLIER_NAMES),
        "mobile": randoms.mobile(),
        "shippingAddress": "House %s, Supplier Road, Dhaka" % randoms.digits(3),
    }
