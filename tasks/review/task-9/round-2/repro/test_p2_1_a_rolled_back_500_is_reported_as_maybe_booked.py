"""P2-1: erp_os's own 500 means the write was rolled back, not that it may exist.

erp_os's create_so (app/services/sales.py:208-258) does not validate customer_id
at all -- it assigns data.customer_id onto the row and flushes. A customer_id
that is not in the customers table therefore violates the FK fk_so_customer
(app/models/sales.py:47-48), which is a SQLAlchemy IntegrityError, which is not
an AppException, which lands in the catch-all handler at app/main.py:212-218 and
comes back as 500 {"error_code":"INTERNAL_ERROR", ...}. app/core/deps.py:45-47
has rolled the transaction back before that response is written.

So this particular 500 is a refusal: nothing was booked, and the right thing to
do is exactly what a 4xx does -- tell the customer the order was not placed, and
let the bot try again with a customer it actually looked up. Instead the tool
returns ORDER_UNKNOWN: "Do not place it again", "a colleague will confirm it
within a few minutes". Nobody will.

The signal that tells this apart from a 502/504 handed back by nginx (which
really does say nothing about what erp_os did) is already in hand: an
application-level 5xx carries erp_os's own error envelope in the body, and
_detail() already captures it.

The developer's own test for this path, test_a_rejected_order_says_nothing_was_
booked, mocks a 400 with '{"detail":"Customer 999 not found."}' -- a response
erp_os has no code to produce. That is why the suite is green here.
"""

from unittest.mock import patch

import httpx  # noqa: F401  (kept so the mock spec in conftest is importable)

from conftest import ERP_INTERNAL_ERROR_BODY, LOGIN, SKU_DETAIL, response

from app.services import api_client
from app.tools import erp


def test_an_error_erp_os_handled_itself_is_not_reported_as_maybe_booked(erp_credentials):
    rolled_back = response({}, 500, text=ERP_INTERNAL_ERROR_BODY)

    with patch.object(
        api_client.httpx, "post", side_effect=[response(LOGIN), rolled_back]
    ) as post:
        with patch.object(api_client.httpx, "get", return_value=response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(9999, [{"sku_id": 201, "quantity": 2}])

    # The write really was attempted, and erp_os really did answer it: this is
    # not a dropped connection, it is a refusal wearing a 500.
    assert any("/api/sales-orders" in call.args[0] for call in post.call_args_list)

    assert answer != erp.ORDER_UNKNOWN, (
        "erp_os answered with its own INTERNAL_ERROR envelope, which means the "
        "request reached the app and app/core/deps.py rolled the transaction "
        "back -- no order exists. The tool still tells the customer to wait for "
        "a colleague to confirm one, and forbids the bot from placing it again."
    )
