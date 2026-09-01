"""The ERP says why it refused; the bot replaces it with a guess.

`JsonApiClient._request` goes out of its way to carry the reason across the
boundary -- `_detail(response)` exists for exactly this, and the comment above it
says so in as many words (api_client.py:255-258):

    # Carry the service's own words: "insufficient stock" and "no such
    # customer" are different answers to give a waiting customer, and a
    # bare status code cannot tell them apart.

`erp_create_sales_order` then drops it. Every refused create becomes the one
constant ORDER_FAILED, and every refused confirm becomes the one constant
`_not_confirmed(document_no)` -- which does not merely omit the reason, it
asserts a different one ("most often this means the branch does not have enough
stock") whether or not that is what erp_os said.

The two bodies below are real: the INVALID_STATUS_TRANSITION one was captured
off erp.kelvinpeng.com on 2026-09-01, the others are erp_os's own error envelope
built from its source. This is not an argument about wording -- it is that two
different, machine-readable answers from the back office arrive at the model as
one identical sentence, so the model cannot act on either.
"""

from unittest.mock import patch

from app.services import api_client, erp_client
from app.tools import erp

from conftest import (
    DRAFT_ORDER,
    LOGIN,
    REAL_BUSINESS_RULE_BODY,
    REAL_INSUFFICIENT_STOCK_BODY,
    REAL_INTERNAL_ERROR_BODY,
    REAL_INVALID_STATUS_BODY,
    SKU_DETAIL,
    erp_error,
    response,
)

ITEMS = [{"sku_id": 201, "quantity": 100}]


def _order_with_confirm_refused(body: str, status_code: int) -> str:
    # Drop the cached token, or the second call in a test skips the login and
    # every canned response below shifts one place -- a green test measuring the
    # wrong thing.
    erp_client.reset()
    posts = [
        response(LOGIN),
        response(DRAFT_ORDER, 201),
        erp_error(body, status_code),
    ]
    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=response(SKU_DETAIL)):
            return erp.erp_create_sales_order(1, ITEMS)


def _order_with_create_refused(body: str, status_code: int) -> str:
    erp_client.reset()
    posts = [response(LOGIN), erp_error(body, status_code)]
    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=response(SKU_DETAIL)):
            return erp.erp_create_sales_order(1, ITEMS)


def test_two_different_confirm_refusals_do_not_collapse_into_one_sentence(erp_credentials):
    """Out of stock in this branch vs. the order is not in DRAFT any more.

    The first is fixable by shipping from Penang, which has 25. The second means
    somebody already confirmed it and the bot must not treat it as a problem at
    all. The model gets the same 4 sentences for both.
    """
    out_of_stock = _order_with_confirm_refused(REAL_INSUFFICIENT_STOCK_BODY, 422)
    wrong_status = _order_with_confirm_refused(REAL_INVALID_STATUS_BODY, 422)

    assert out_of_stock != wrong_status, (
        "erp_os gave two different reasons and the bot said the same thing twice:\n"
        f"  {out_of_stock}"
    )


def test_a_refused_confirm_passes_on_what_the_erp_actually_said(erp_credentials):
    """`_not_confirmed` does not just omit the reason, it invents one."""
    answer = _order_with_confirm_refused(REAL_INSUFFICIENT_STOCK_BODY, 422)

    assert "INSUFFICIENT_STOCK" in answer or "Insufficient stock" in answer, answer


def test_two_different_create_refusals_do_not_collapse_into_one_sentence(erp_credentials):
    """A closed accounting period vs. a customer_id that is not in the table.

    Both are certain -- nothing was booked either way -- but one is answered by
    calling erp_find_customer and retrying, and the other cannot be answered by
    the bot at all. ORDER_FAILED is returned for both.
    """
    closed_period = _order_with_create_refused(REAL_BUSINESS_RULE_BODY, 422)
    unknown_customer = _order_with_create_refused(REAL_INTERNAL_ERROR_BODY, 500)

    assert closed_period != unknown_customer, (
        "erp_os gave two different reasons and the bot said the same thing twice:\n"
        f"  {closed_period}"
    )
