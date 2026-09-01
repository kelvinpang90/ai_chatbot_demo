from __future__ import annotations

import re

# Both back offices store whatever the salesperson typed -- "+60 17-394 8123",
# "017-3948123" and "60173948123" are all the same person. Comparing the tail
# sidesteps both the punctuation and the country code, and 8 digits is long
# enough not to collide in books this size.
PHONE_SUFFIX_DIGITS = 8

# Below this a term is a house number or an order quantity, not a phone number.
MIN_PHONE_DIGITS = 7

# Both erp_os and crm_os cap a page at 100 server-side regardless of what we ask.
PAGE_SIZE = 100

# A phone scan pages through the whole book, so it needs a stop. 500 rows is far
# more than either demo database holds, and a miss reads as "not on file yet",
# which is the right answer for a number nobody has recorded.
MAX_SCAN_PAGES = 5

# Digits plus the punctuation people put between them. A name has none of this.
_PHONE_SHAPED = re.compile(r"^[\d\s+()\-.]+$")


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def looks_like_a_phone(term: str) -> bool:
    term = term.strip()
    return bool(_PHONE_SHAPED.match(term)) and len(digits(term)) >= MIN_PHONE_DIGITS


def matches(stored: str, term: str) -> bool:
    """Is this stored number the one the term is asking about?

    Neither service can search on phone, so both clients pull rows and compare
    here. One implementation, because "which digits count" is a rule that must
    not be allowed to drift apart between the ERP and the CRM.
    """
    wanted = digits(term)[-PHONE_SUFFIX_DIGITS:]
    return bool(wanted) and digits(stored).endswith(wanted)
