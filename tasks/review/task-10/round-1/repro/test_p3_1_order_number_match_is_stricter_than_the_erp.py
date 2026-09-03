"""An order number the ERP itself matched is thrown away by the exact compare.

`ErpClient.sales_order_for_customer` asks erp_os for `?search=<order_no>`, which
is a case-insensitive LIKE (`repositories/sales_order.py`: `document_no.ilike`),
and then keeps only rows whose `document_no` is byte-identical to what it was
given. So a number that differs from the ERP's own only in case or in
surrounding whitespace comes back from the search and is then discarded, and the
customer is told their order does not exist -- on the one step of the demo where
a document was promised.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
import pytest

from app.config import settings
from app.services import api_client, erp_client, outbox, whatsapp_media
from app.tools import erp

_LOGIN = {"access_token": "acc", "refresh_token": "ref", "expires_in": 900}

SO_ROW = {"id": 77, "document_no": "SO-2026-0042", "status": "CONFIRMED"}
SO_DETAIL = {
    **SO_ROW,
    "customer_id": 3,
    "lines": [{"id": 501, "qty_ordered": "3.0000", "qty_shipped": "0.0000"}],
}
INVOICE = {
    "id": 9,
    "document_no": "INV-2026-0007",
    "status": "VALIDATED",
    "uin": "MY-UIN-8891234",
    "currency": "MYR",
    "total_incl_tax": "986.7000",
    "lines": [],
}


def _response(payload: dict, status_code: int = 200) -> Mock:
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = ""
    response.raise_for_status.return_value = None
    response.headers = {"content-type": "application/json"}
    return response


@pytest.fixture(autouse=True)
def _client_and_channel():
    erp_client.reset()
    with patch.object(settings, "erp_email", "reviewer@example.com"):
        with patch.object(settings, "erp_password", "irrelevant"):
            outbox.begin()
            yield
    outbox.close()
    erp_client.reset()


@pytest.mark.parametrize(
    "as_the_model_typed_it",
    ["so-2026-0042", " SO-2026-0042"],
)
def test_the_erp_found_the_order_so_the_tool_must_not_report_it_missing(as_the_model_typed_it):
    """erp_os's LIKE is case-insensitive and ignores nothing else, so the search
    below is what the live service really answers for both spellings."""
    posts = [
        _response(_LOGIN),
        _response({"id": 300, "document_no": "DO-2026-0031"}, 201),
        _response(INVOICE, 201),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(
            api_client.httpx,
            "get",
            side_effect=[_response({"items": [SO_ROW]}), _response(SO_DETAIL)],
        ):
            with patch.object(whatsapp_media, "upload_media", return_value="media-1"):
                answer = erp.erp_generate_einvoice(as_the_model_typed_it, 3)

    assert answer != erp.NO_SUCH_ORDER, (
        f"the ERP returned {SO_ROW['document_no']} for {as_the_model_typed_it!r} "
        "and the tool discarded it"
    )
