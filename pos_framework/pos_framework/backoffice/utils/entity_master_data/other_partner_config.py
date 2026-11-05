# ============================================================
# Test data for Other Partner (Supplier & Customer) create.
# Converted from the source suite; office/territory now come from
# the profile.
# ============================================================

from backoffice.utils import randoms

PARTNER_NAMES = [
    "Ganges Traders", "Halda Enterprise", "Teesta Distribution", "Barak Store",
    "Kushiyara Mart", "Feni & Sons", "Matamuhuri Retail", "Sangu Enterprise",
    "Naaf Trading", "Karotoya Wholesale",
]


def generate_other_partner_data(profile):
    """One Other Partner create run's worth of data."""
    partner_name = randoms.unique_name(PARTNER_NAMES)

    data = {
        "office": profile.data("office"),
        "partnerName": partner_name,
        "partnerBillingName": partner_name,
        "mobile": randoms.mobile(),
        "shippingAddress": "House %s, Partner Road, Dhaka" % randoms.digits(3),
    }
    # This partner type draws from the same shared master data Customer
    # create does - the same Territory list, the same Customer Point.
    data.update(profile.data("customer", default={}))
    return data
