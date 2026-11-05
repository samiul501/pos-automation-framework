# ============================================================
# CREDIT CONFIG - credit-sales-only data and settings. Kept apart
# from the parent config.py so the existing suites are untouched.
#
# NOTHING here is a fixed customer or a fixed expected total: the
# suite creates its own customer every run (unique mobile number)
# and derives every expected figure from what it just created or
# from the database. These values are only the INPUTS a run starts
# from, and the labels/ids needed to drive the two UIs.
# ============================================================

# ---- what the run creates ------------------------------------------
# The first agreed run uses 5000 / 10 days; CREDIT_LIMIT_CHOICES and
# CREDIT_DAYS_CHOICES let later runs vary it without touching code.
# credit_data.new_customer_spec() picks from these.
DEFAULT_CREDIT_LIMIT = 5000
DEFAULT_CREDIT_DAYS = 10
CREDIT_LIMIT_CHOICES = [3000, 5000, 8000, 10000]
CREDIT_DAYS_CHOICES = [7, 10, 15, 30]

# Name prefix so a run's customers are recognisable in the backend
# (and so a stale one can be spotted later): AUTO-CREDIT-<stamp>.
CUSTOMER_NAME_PREFIX = "AUTO-CREDIT"

# ---- where the run happens -----------------------------------------
# The exe on this machine is registered to counter "sami2" -> office 9
# "Dhanmondi Outlet", branch 1 "Demo Super Shop". The customer
# must be created under the SAME office or the exe will not find it.
OFFICE_NAME = "Dhanmondi Outlet"
OFFICE_ID = 9
BRANCH_ID = 1
BRANCH_NAME = "Demo Super Shop"
COUNTER_ID = 20183

# ---- backend web: the create-customer form -------------------------
# IMPORTANT (confirmed live 2026-09-22): opening
# /config/custoemerProfile/create by URL renders a STRIPPED form -
# no Credit Limit, no Credit Days, no Territory. The fields are gated
# behind permissions that are only loaded when the page is reached
# through the menu, so credit_web.open_create_customer() always
# navigates Configuration -> Customer Profile -> Customer.
ROUTE_CUSTOMER_PROFILE = "/config/custoemerProfile"
MENU_CONFIGURATION = "Configuration"
CREATE_BUTTON_TEXT = "Customer"

# Only two fields carry the red required star beyond the obvious
# Office / Partner Name / Mobile No: Territory and Customer Point.
TERRITORY_OPTION = "ORG-AGORA - Agora Limited"
CUSTOMER_POINT_OPTION = "Membership-1 x 2"

# react-select container ids on that form (read live off the page)
SELECT_OFFICE = "office"
SELECT_TERRITORY = "territory"
SELECT_CUSTOMER_POINT = "customerPoint"

# plain inputs, by name attribute
INPUT_PARTNER_NAME = "partnerName"
INPUT_BILLING_NAME = "partnerBillingName"
INPUT_MOBILE = "mobileNo"
INPUT_CREDIT_LIMIT = "creditLimit"
INPUT_CREDIT_DAYS = "paymentDays"

# ---- exe: the Sales Collection screen -------------------------------
# Left nav entry (no automation id - matched by name), the customer
# search box, and the four cards that must mirror the database.
EXE_SALES_COLLECTION_NAV = "Sales Collection"

# ---- tolerances ------------------------------------------------------
# Money is compared to the paisa; the UI prints 2 decimals.
MONEY_TOLERANCE = 0.01
