"""Shared fixtures for round 2's reproductions.

Everything here is either a payload the live erp.kelvinpeng.com actually returns
(checked on 2026-09-01) or a real httpx exception object. Nothing asserts about
an exception type the reviewed code chose to catch -- round 1's lesson.
"""

from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import erp_client

LOGIN = {"access_token": "acc", "refresh_token": "ref", "expires_in": 900}

# GET https://erp.kelvinpeng.com/api/skus/201, trimmed to the keys the order line
# reads. Live, 2026-09-01.
SKU_DETAIL = {
    "id": 201,
    "code": "SKU-ELE-0001",
    "name": "Sony WF-C710N Wireless Earbuds",
    "base_uom_id": 1,
    "tax_rate_id": 1,
    "unit_price_excl_tax": "299.0000",
    "unit_price_incl_tax": "328.9000",
    "price_tax_inclusive": False,
    "currency": "MYR",
}

# What erp_os itself puts in the body of a 500. app/main.py:212-218 catches every
# unhandled exception and answers with this envelope; app/core/deps.py:45-47 has
# already rolled the request's transaction back by then.
ERP_INTERNAL_ERROR_BODY = (
    '{"error_code":"INTERNAL_ERROR","message":"An unexpected error occurred.",'
    '"i18n_key":"errors.internal_error","i18n_args":{},'
    '"request_id":"69d83023-2055-4426-a19c-7f085cc0a4e7",'
    '"timestamp":"2026-09-01T12:37:38.401887+00:00","detail":null}'
)


def response(payload, status_code=200, text=""):
    mock = Mock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = payload
    mock.text = text
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def erp_credentials():
    with patch.object(erp_client.settings, "erp_email", "tester@example.test"):
        with patch.object(erp_client.settings, "erp_password", "not-a-real-password"):
            erp_client.reset()
            yield
            erp_client.reset()
