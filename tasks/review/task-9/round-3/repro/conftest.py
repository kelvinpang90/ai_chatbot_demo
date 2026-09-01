"""Shared fixtures for round 3's reproductions.

Every payload below was taken off the live erp.kelvinpeng.com on 2026-09-01, or
copied verbatim from erp_os's own source. Nothing here is an exception type the
reviewed code chose to catch -- rounds 1 and 2 both got burned by that.
"""

from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import erp_client

LOGIN = {"access_token": "acc", "refresh_token": "ref", "expires_in": 900}

# GET https://erp.kelvinpeng.com/api/skus/201, trimmed to the keys an order line
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

# POST /api/sales-orders answers with SalesOrderDetail (routers/sales_order.py:50).
DRAFT_ORDER = {
    "id": 99999,
    "document_no": "SO-2026-00001",
    "status": "DRAFT",
    "customer_id": 1,
    "warehouse_id": 1,
}

# Captured live on 2026-09-01 by POSTing /api/sales-orders/247/confirm at an
# order that was already CONFIRMED. Status 422, order left untouched.
REAL_INVALID_STATUS_BODY = (
    '{"error_code":"INVALID_STATUS_TRANSITION",'
    '"message":"Cannot confirm a sales order in CONFIRMED status.",'
    '"i18n_key":"errors.invalid_status_transition","i18n_args":{},'
    '"request_id":"a3afd5da-72f5-4855-bab4-a48890fa25ca",'
    '"timestamp":"2026-09-01T13:14:56.583638+00:00","detail":null}'
)

# The other way a confirm is refused. Message format from erp_os
# services/inventory.py:281-290, error code from core/exceptions.py:137-139,
# 422 from BusinessRuleError (core/exceptions.py:78-83).
REAL_INSUFFICIENT_STOCK_BODY = (
    '{"error_code":"INSUFFICIENT_STOCK",'
    '"message":"Insufficient stock for sku=201 warehouse=1: requested 100, available 42.",'
    '"i18n_key":"errors.insufficient_stock","i18n_args":{},'
    '"request_id":"1c0f9d64-31e1-4a2f-9e1a-1d7d0f2a55b1",'
    '"timestamp":"2026-09-01T13:20:02.113400+00:00",'
    '"detail":{"sku_id":201,"warehouse_id":1,"requested":"100","available":"42"}}'
)

# A create refused by a business rule (erp_os core/exceptions.py:78-83).
REAL_BUSINESS_RULE_BODY = (
    '{"error_code":"BUSINESS_RULE_VIOLATION",'
    '"message":"The accounting period for 2026-09-01 is closed.",'
    '"i18n_key":"errors.business_rule_violation","i18n_args":{},'
    '"request_id":"8f4b1f5a-7a34-4f3e-8f0a-2b1c9d0e4a77",'
    '"timestamp":"2026-09-01T13:21:44.000000+00:00","detail":null}'
)

# What erp_os puts in the body of a 500. main.py:212-218 catches every unhandled
# exception; core/deps.py:45-47 has already rolled the transaction back by then.
# An unknown customer_id arrives here as a foreign key violation.
REAL_INTERNAL_ERROR_BODY = (
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


def erp_error(body: str, status_code: int):
    """A refusal shaped exactly like the one erp_os sends: JSON body, JSON text."""
    import json as _json

    return response(_json.loads(body), status_code, text=body)


@pytest.fixture
def erp_credentials():
    with patch.object(erp_client.settings, "erp_email", "tester@example.test"):
        with patch.object(erp_client.settings, "erp_password", "not-a-real-password"):
            erp_client.reset()
            yield
            erp_client.reset()
