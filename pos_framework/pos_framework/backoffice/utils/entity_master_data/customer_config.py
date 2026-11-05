# ============================================================
# Test data for Customer create.
#
# Converted from the source suite. It used to read office and
# territory from test_data/<env>/master_data.py, which only ever
# described StoreB; it now reads them from the profile, so the same
# generator feeds a DemoStore run with DemoStore's values.
# ============================================================

from backoffice.utils import randoms

CUSTOMER_NAMES = [
    "Rahman Traders", "Karim Enterprise", "Noor Distribution", "Alam Store",
    "Sultana Mart", "Chowdhury & Sons", "Hasan Retail", "Begum Enterprise",
    "Islam Trading", "Ahmed Wholesale",
]


def generate_customer_data(profile):
    """One Customer create run's worth of data."""
    partner_name = randoms.unique_name(CUSTOMER_NAMES)

    data = {
        "office": profile.data("office"),
        "partnerName": partner_name,
        # Billing name deliberately matches the partner name: the list
        # shows both columns and the row assertion accepts either.
        "partnerBillingName": partner_name,
        "mobile": randoms.mobile(),
        "shippingAddress": "House %s, Test Road, Dhaka" % randoms.digits(3),
    }
    # Whatever this environment lists under master["customer"] - territory
    # everywhere, plus Customer Point and the credit terms on the apps that
    # ask for them - comes through under its own key, so the form recipe
    # can name it without this file knowing those fields exist.
    data.update(profile.data("customer", default={}))
    return data
