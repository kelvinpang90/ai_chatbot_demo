from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import crm_client, erp_client

LOGIN = {"access_token": "acc", "refresh_token": "ref", "expires_in": 900}

# The real /api/skus/201 payload, trimmed to the keys the order line reads.
# Taken from a live GET against erp.kelvinpeng.com on 2026-09-01.
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


@pytest.fixture
def crm_credentials():
    with patch.object(crm_client.settings, "crm_email", "tester@example.test"):
        with patch.object(crm_client.settings, "crm_password", "not-a-real-password"):
            crm_client.reset()
            yield
            crm_client.reset()
