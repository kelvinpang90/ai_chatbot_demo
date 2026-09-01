"""P1-1: a catalogue GET that times out is reported as "the order may exist".

erp_create_sales_order does not start with the POST. Before anything is written
it reads /api/skus/{id} once per line, to price the order from the catalogue
rather than from the conversation. Those reads go through the same
JsonApiClient._request, and _request computes `may_have_landed` from the
exception alone -- it never looks at the HTTP method. A read timeout on a GET
therefore reaches the tool carrying may_have_landed=True, and the tool has
exactly one thing to say about that: ORDER_UNKNOWN.

Nothing was posted. The customer is told their order is being checked and a
colleague will confirm it, and the model is told "Do not place it again", so the
sale is lost silently and the bot will refuse to retry the one thing that would
save it.

The input is a real httpx.ReadTimeout on the catalogue read -- what a back
office that has gone slow produces. REQUEST_TIMEOUT_SECONDS = 15 exists
precisely because that happens.
"""

from unittest.mock import patch

import httpx

from conftest import LOGIN, response

from app.services import api_client
from app.tools import erp


def test_a_read_that_timed_out_before_the_write_does_not_claim_the_order_may_exist(
    erp_credentials,
):
    with patch.object(api_client.httpx, "post", side_effect=[response(LOGIN)]) as post:
        with patch.object(api_client.httpx, "get", side_effect=httpx.ReadTimeout("timed out")):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 201, "quantity": 2}])

    # The objective fact this hangs on: the only POST that happened was the
    # login. /api/sales-orders was never called, so no order can exist.
    order_writes = [call for call in post.call_args_list if "/api/sales-orders" in call.args[0]]
    assert order_writes == [], "the set-up is wrong: an order really was posted"

    assert answer != erp.ORDER_UNKNOWN, (
        "the tool told the model the order may exist and must not be placed again, "
        "but the only request that left this process was a catalogue GET -- "
        "/api/sales-orders was never called. The customer is promised an order "
        "nobody will find, and the bot is instructed not to retry."
    )
