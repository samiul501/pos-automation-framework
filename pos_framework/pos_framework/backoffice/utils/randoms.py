# ============================================================
# The random bits every data builder needs.
#
# In the source suite each generator carried its own private copy
# of _random_digits / _random_item. Six identical copies is six
# places to fix, so they live here once and the generators import
# them. The name pools stay with their own generator - those are
# domain data, not a utility.
# ============================================================

import random
import string


def digits(length):
    """A string of `length` random digits (0-9)."""
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def pick(items):
    """A random element of `items`."""
    return items[random.randint(0, len(items) - 1)]


def unique_name(pool, width=4):
    """e.g. "Rice_4821" - a name from the pool plus digits, so every run
    creates a record that can be told apart from the last one's."""
    return "%s_%s" % (pick(pool), digits(width))


def mobile():
    """A Bangladeshi mobile number in the shape both apps accept."""
    return "018" + digits(8)


def strong_password(length=10):
    """A password that registers as "Strong" on the Employee create User
    Account form, which requires upper + lower + digit + special char.

    Learned the hard way in the source suite: a plain digit string like
    "123456" is flagged "Weak password" and silently blocks the save - no
    error toast, the button just does nothing.
    """
    required = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%"),
    ]
    pool = string.ascii_letters + string.digits
    required += [random.choice(pool) for _ in range(length - len(required))]
    random.shuffle(required)
    return "".join(required)
