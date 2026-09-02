"""P2-1: MAX_AMOUNT leaves a gap the guard exists to close.

`crm_client.MAX_AMOUNT = 10**13` is commented "`deals.amount` is DECIMAL(15, 2),
so this is the first value it cannot hold", and `_usable` admits anything below
it. But MySQL rounds to the scale before checking the range, so every value from
9999999999999.995 upward rounds to 10000000000000.00 and overflows. The guard's
own stated purpose -- "a title one character too long is not a truncated card, it
is a 500 and a lead the salesperson never sees" -- is exactly what leaks here.

Not a value a customer produces; the point is that the constant does not mean
what it says, and it is the one hole that let P1-1 be demonstrated against the
live service rather than argued about:

    amount: 9999999999999.998 < MAX_AMOUNT: True
    crm api: POST /api/contacts returned 500: Internal Server Error
    contacts now on file with that phone: []
"""
from unittest.mock import patch

import pytest

from app.services import crm_client
from app.tools import crm

# The largest float below MAX_AMOUNT; DECIMAL(15, 2) rounds it to 10**13.
ROUNDS_OVER = 9999999999999.998


@pytest.fixture(autouse=True)
def _fresh_client():
    crm_client.reset()
    yield
    crm_client.reset()


def _get(path, params=None):
    """The two GET routes, in the shape they answer past `_unwrap`."""
    if path == "/api/contacts":
        return {"data": []}
    if path == "/api/deals":
        return []
    raise AssertionError(f"unexpected GET {path}")


def test_an_amount_that_rounds_past_the_column_never_reaches_the_crm():
    assert ROUNDS_OVER < crm_client.MAX_AMOUNT

    with patch.object(crm_client.CrmClient, "get", side_effect=_get):
        with patch.object(crm_client.CrmClient, "post") as post:
            answer = crm.crm_create_lead(
                "Ahmad Faizal", "+60 12-333 4444", "3 units of earbuds", ROUNDS_OVER
            )

    assert post.call_args_list == []
    assert answer == crm.BAD_LEAD
