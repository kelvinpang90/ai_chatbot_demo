"""A write that timed out is reported to the customer as a write that never happened.

`JsonApiClient.post` documents the opposite intent:

    Nothing else is retried -- a timeout mid-write may well have landed, and we
    would rather report a failure the human can check than create a second order.

But the only word the tool has for "the POST raised" is ORDER_FAILED, and
ORDER_FAILED says, verbatim:

    Nothing was booked -- tell the customer their order was not placed.

REQUEST_TIMEOUT_SECONDS is 15. `POST /api/sales-orders` on erp.kelvinpeng.com
does a document-number allocation, a tax-rate load, an insert and a re-read
inside one transaction; a 15s ceiling on that over the public internet is a real
timeout, not a hypothetical one. When it fires after the row has been committed,
the bot tells the customer their order was not placed while the salesperson's
ERP screen shows a fresh DRAFT order with their name on it -- and a customer who
believes nothing happened will ask again, which books it twice.
"""

from unittest.mock import patch

import httpx

from app.services import api_client
from app.tools import erp

from conftest import LOGIN, SKU_DETAIL, response


def test_a_timed_out_write_is_not_reported_as_nothing_was_booked(erp_credentials):
    # httpx.ReadTimeout is what a slow erp_os actually raises: the request went
    # out, the response never came back, and nothing here can tell whether the
    # order was committed on the far side.
    posts = [response(LOGIN), httpx.ReadTimeout("timed out")]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 201, "quantity": 2}])

    assert "Nothing was booked" not in answer, (
        "the tool told the model the order definitely was not placed, but a "
        "ReadTimeout on the POST means the order may well exist in erp_os"
    )
    assert "was not placed" not in answer
