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


# Meta's business-scoped user id: an ISO 3166 alpha-2 country code, a period,
# then up to 128 alphanumerics -- "US.13491208655302741918". Since 2026 it rides
# on every inbound message, and it is all we get from a customer who has hidden
# their phone number behind a username.
#
# The period is what makes the two unmistakable: no phone number, in any of the
# ways people write one, contains a period followed by letters and digits.
_BSUID = re.compile(r"^[A-Za-z]{2}\.[A-Za-z0-9]{1,128}$")


def is_bsuid(value: str) -> bool:
    """Is this Meta's user id rather than a phone number?

    Asked wherever an identifier has to be filed, matched or addressed, so that
    "which of the two is this" is decided in one place and cannot drift.
    """
    return bool(_BSUID.match((value or "").strip()))


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


# A country code is one to three digits (ITU-T E.164), so one number written
# nationally and internationally differs by at most three leading digits, plus
# the trunk "0" the national form puts in their place.
MAX_COUNTRY_CODE_DIGITS = 3


def is_the_same_number(stored: str, term: str) -> bool:
    """Are these certainly one number -- strictly enough to write to the record?

    `matches` compares the last eight digits, which is right for a lookup: a
    salesperson's "017-3948123" and WhatsApp's "60173948123" are one person, and
    a wrong hit there is visible in the answer the model reads. It is not right
    for choosing whose record to write to. Eight digits collide across country
    codes -- a Shah Alam landline "03-8555 1515" and a San Diego
    "+1-858-555-1515" share their tail, and this CRM's demo book holds that
    exact pair -- so the loose rule would file one customer's enquiry onto a
    stranger, silently, on the board a salesperson works from.

    This requires the whole number to agree, allowing only the difference that
    is genuinely notation. It still cannot tell a nine-digit national number
    from a foreign one whose country code completes it: a tighter net, not a
    proof of identity, which is why the caller treats "not the same" as "make a
    new record" rather than as a failure.
    """
    a, b = digits(stored).lstrip("0"), digits(term).lstrip("0")
    if not a or not b:
        return False
    longer, shorter = (a, b) if len(a) >= len(b) else (b, a)
    return longer.endswith(shorter) and len(longer) - len(shorter) <= MAX_COUNTRY_CODE_DIGITS
