import json
from unittest.mock import patch

import httpx
import pytest

from app.services import api_client, erp_client
from app.services.api_client import ApiClientError
from app.tools import erp

SKU_ROW = {
    "id": 12,
    "code": "SKU-00012",
    "name": "TWS Earbuds Pro",
    "name_zh": "无线耳机 Pro",
    "unit_price_excl_tax": "89.00",
    "unit_price_incl_tax": "94.34",
    "price_tax_inclusive": False,
    "currency": "MYR",
    "costing_method": "weighted_average",
    "safety_stock": "10",
}

MATRIX_ROW = {
    "sku_id": 12,
    "sku_code": "SKU-00012",
    "sku_name": "TWS Earbuds Pro",
    "safety_stock": "10",
    "warehouses": [
        {"warehouse_id": 1, "warehouse_name": "KL Main", "on_hand": "20", "available": "18"},
        {"warehouse_id": 2, "warehouse_name": "Penang", "on_hand": "5", "available": "4"},
    ],
}


@pytest.fixture(autouse=True)
def _fresh_client():
    erp_client.reset()
    yield
    erp_client.reset()


def test_search_hits_the_sku_route_and_returns_only_what_a_customer_would_ask():
    with patch.object(erp_client.ErpClient, "get", return_value={"items": [SKU_ROW]}) as get:
        payload = json.loads(erp.erp_search_sku("earbuds"))

    assert get.call_args.args[0] == "/api/skus"
    assert get.call_args.kwargs["params"]["search"] == "earbuds"
    assert payload == [
        {
            "sku_id": 12,
            "code": "SKU-00012",
            "name": "TWS Earbuds Pro",
            "name_zh": "无线耳机 Pro",
            "unit_price": "89.00",
            "currency": "MYR",
        }
    ]


def test_search_quotes_the_tax_inclusive_price_when_that_is_how_it_is_sold():
    inclusive = {**SKU_ROW, "price_tax_inclusive": True}

    with patch.object(erp_client.ErpClient, "get", return_value={"items": [inclusive]}):
        payload = json.loads(erp.erp_search_sku("earbuds"))

    assert payload[0]["unit_price"] == "94.34"


def test_inventory_asks_across_every_warehouse_and_totals_what_can_be_sold():
    with patch.object(erp_client.ErpClient, "get", return_value={"rows": [MATRIX_ROW]}) as get:
        payload = json.loads(erp.erp_get_inventory("SKU-00012"))

    assert get.call_args.args[0] == "/api/inventory/branch-matrix"
    assert get.call_args.kwargs["params"]["sku_query"] == "SKU-00012"
    # Available, not on-hand: 25 are in the building but 3 belong to other orders.
    assert payload[0]["total_available"] == 22
    assert [cell["warehouse"] for cell in payload[0]["by_warehouse"]] == ["KL Main", "Penang"]


def test_an_empty_result_says_so_rather_than_returning_nothing():
    """The model has to be able to tell "no such product" from "the lookup broke"."""
    with patch.object(erp_client.ErpClient, "get", return_value={"items": []}):
        assert erp.erp_search_sku("no-such-thing") == erp.NOT_FOUND

    with patch.object(erp_client.ErpClient, "get", return_value={"rows": []}):
        assert erp.erp_get_inventory("no-such-thing") == erp.NOT_FOUND


def test_an_unreachable_erp_becomes_an_answer_the_bot_can_relay():
    with patch.object(erp_client.ErpClient, "get", side_effect=ApiClientError("boom")):
        assert erp.erp_search_sku("earbuds") == erp.UNAVAILABLE
        assert erp.erp_get_inventory("earbuds") == erp.UNAVAILABLE


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", "https://erp"), response=httpx.Response(429)
        ),
    ],
    ids=["dead-host", "timeout", "rate-limited"],
)
def test_a_real_transport_failure_degrades_instead_of_escaping(failure):
    """Regression: these three used to escape the tool and blow up the reply.

    The original tests raised ApiClientError -- the type the tool had chosen to
    catch -- so they passed while every failure that actually happens went
    uncaught. Patch httpx itself, not the exception we hoped for.
    """
    with patch.object(api_client.httpx, "post", side_effect=failure):
        assert erp.erp_search_sku("fan") == erp.UNAVAILABLE
        assert erp.erp_get_inventory("fan") == erp.UNAVAILABLE


def test_a_typo_in_the_base_url_degrades_instead_of_escaping():
    """The whole path, not just the client: a bad ERP_BASE_URL must reach the bot
    as "I could not check that", the same as any other outage."""
    with patch.object(erp_client.settings, "erp_base_url", "http://[::1"):
        with patch.object(erp_client.settings, "erp_email", "a@b.c"):
            with patch.object(erp_client.settings, "erp_password", "x"):
                erp_client.reset()
                assert erp.erp_search_sku("fan") == erp.UNAVAILABLE
                assert erp.erp_get_inventory("fan") == erp.UNAVAILABLE


def test_the_client_is_shared_so_the_cached_token_is_too():
    assert erp_client.client() is erp_client.client()


def test_both_tools_are_declared_with_a_schema_the_model_can_read():
    names = {tool.name for tool in erp.TOOLS}
    assert names == {"erp_search_sku", "erp_get_inventory"}
    for tool in erp.TOOLS:
        assert tool.input_schema["properties"]  # arguments made it into the schema
        assert tool.description
