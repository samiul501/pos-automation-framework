# ============================================================
# Test data for Employee create.
#
# Converted from the source suite. Designation and Employee Type
# were literals ("QA", "Full Time") because the suite only ever
# ran against StoreB; they are now profile lookups with those same
# values as the default, so an environment that names them
# differently only has to say so in its profile.
# ============================================================

from backoffice.utils import randoms

FIRST_NAMES = [
    "Habib", "Raisa", "Tanvir", "Nusrat", "Sabbir",
    "Farzana", "Imran", "Mahmud", "Sadia", "Rafiq",
]

LAST_NAMES = [
    "Ahmed", "Rahman", "Islam", "Hossain", "Chowdhury",
    "Karim", "Alam", "Siddique", "Khan", "Hasan",
]


def generate_employee_data(profile):
    """One Employee create run's worth of personal-info data."""
    return {
        "employeeId": "X-" + randoms.digits(5),
        "name": "%s %s" % (randoms.pick(FIRST_NAMES), randoms.pick(LAST_NAMES)),
        "designation": profile.data("employee", "designation", default="QA"),
        "mobile": randoms.mobile(),
        "employeeType": profile.data("employee", "employeeType", default="Full Time"),
        "office": profile.data("office"),
        "nid": randoms.digits(16),
        "supervisor": profile.data("employee", "supervisor"),
        "lineManager": profile.data("employee", "lineManager"),
    }


def generate_user_account_data(profile):
    """The Business Unit / Office / Warehouse permission row for the "User"
    account section.

    Kept separate from generate_employee_data() because it maps to a
    distinct part of the form that can be skipped entirely - see
    EmployeeCreatePage.enable_user_account.
    """
    return {
        "password": randoms.strong_password(),
        "businessUnit": profile.data("employee", "businessUnit"),
        "office": profile.data("office"),
        "warehouse": profile.data("employee", "warehouse"),
    }
