import json
from datetime import datetime
from unittest.mock import Mock, patch

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


def test_every_tool_is_declared_with_a_schema_the_model_can_read():
    names = {tool.name for tool in erp.TOOLS}
    assert names == {"erp_search_sku", "erp_get_inventory", "erp_create_sales_order"}
    for tool in erp.TOOLS:
        assert tool.input_schema["properties"]  # arguments made it into the schema
        assert tool.description


def test_the_order_tool_describes_its_line_items_field_by_field():
    """A bare `array of object` would leave the model guessing the key names."""
    schema = next(t for t in erp.TOOLS if t.name == "erp_create_sales_order").input_schema
    line = schema["$defs"]["OrderLine"]

    assert set(line["properties"]) == {"sku_id", "quantity"}
    assert schema["properties"]["items"]["items"]["$ref"].endswith("OrderLine")
    # Naming a warehouse is optional; ordering something is not.
    assert set(schema["required"]) == {"customer_id", "items"}


# -- writing an order --------------------------------------------------------
#
# These drive httpx itself rather than stubbing ErpClient.post. A test that
# asserts "the method I wrote was called" passes whether or not the request it
# builds is one erp_os would accept; these fail if the route, the payload shape
# or the order of the two writes is wrong.

SKU_DETAIL = {
    **SKU_ROW,
    "base_uom_id": 1,
    "tax_rate_id": 4,
}

CONFIRMED_ORDER = {
    "id": 77,
    "document_no": "SO-2026-0042",
    "status": "CONFIRMED",
    "customer_id": 3,
    "customer_name": "Tan Ah Kau",
    "warehouse_name": "Main Warehouse - Kuala Lumpur",
    "currency": "MYR",
    "total_incl_tax": "986.70",
    "lines": [
        {
            "sku_code": "SKU-00012",
            "sku_name": "TWS Earbuds Pro",
            "qty_ordered": "3.0",
            "unit_price_excl_tax": "89.0000",
            "line_total_incl_tax": "986.70",
        }
    ],
}
DRAFT_ORDER = {**CONFIRMED_ORDER, "status": "DRAFT"}

_LOGIN = {"access_token": "acc", "refresh_token": "ref", "expires_in": 900}


def _response(payload: dict, status_code: int = 200, text: str = "") -> Mock:
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = text
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def _credentials():
    """The client refuses to log in without these, so a write test needs them."""
    with patch.object(erp_client.settings, "erp_email", "tester@example.test"):
        with patch.object(erp_client.settings, "erp_password", "not-a-real-password"):
            erp_client.reset()
            yield


def test_an_order_is_created_then_confirmed_with_prices_from_the_catalogue(_credentials):
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)) as get:
            payload = json.loads(
                erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}], warehouse_id=2)
            )

    # The line was priced from /api/skus/12, not from anything the caller said.
    assert get.call_args.args[0].endswith("/api/skus/12")
    create, confirm = post.call_args_list[1], post.call_args_list[2]
    assert create.args[0].endswith("/api/sales-orders")
    body = create.kwargs["json"]
    assert body["customer_id"] == 3
    assert body["warehouse_id"] == 2
    assert body["lines"] == [
        {
            "sku_id": 12,
            "uom_id": 1,
            "tax_rate_id": 4,
            "qty_ordered": "3.0",
            "unit_price_excl_tax": "89.00",
        }
    ]
    # Confirming is what reserves the stock; a DRAFT order holds nothing.
    assert confirm.args[0].endswith("/api/sales-orders/77/confirm")
    assert payload["order_no"] == "SO-2026-0042"
    assert payload["status"] == "CONFIRMED"
    assert payload["customer"] == "Tan Ah Kau"
    assert payload["lines"][0]["qty"] == "3.0"


def test_the_order_is_dated_in_the_shop_s_own_timezone(_credentials):
    """The VPS is on UTC; before 8am local that is still yesterday's date."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    expected = datetime.now(erp_client.MALAYSIA_TIME).date().isoformat()
    assert post.call_args_list[1].kwargs["json"]["business_date"] == expected


def test_the_order_ships_from_the_main_branch_when_no_warehouse_is_named(_credentials):
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert post.call_args_list[1].kwargs["json"]["warehouse_id"] == erp_client.DEFAULT_WAREHOUSE_ID


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"sku_id": 12, "quantity": 0}],
        [{"sku_id": 12, "quantity": -2}],
        [{"sku_id": 12}],
        [{"sku_id": "not-a-number", "quantity": 1}],
        ["earbuds"],
    ],
    ids=["empty", "zero-qty", "negative-qty", "no-qty", "unparsable-sku", "not-an-object"],
)
def test_an_unusable_order_is_refused_before_anything_is_written(_credentials, items):
    with patch.object(api_client.httpx, "post") as post:
        assert erp.erp_create_sales_order(3, items) == erp.BAD_ITEMS

    # The point is not the message, it is that nothing reached the ERP.
    assert post.call_count == 0


def test_a_rejected_order_says_nothing_was_booked(_credentials):
    """erp_os refusing the write -- an unknown customer, a closed period."""
    rejected = _response({}, 400, text='{"detail":"Customer 999 not found."}')

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), rejected]):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            assert erp.erp_create_sales_order(999, [{"sku_id": 12, "quantity": 1}]) == (
                erp.ORDER_FAILED
            )


def test_an_order_that_could_not_be_confirmed_is_reported_by_number(_credentials):
    """The dangerous half-success: the row exists, the stock is not reserved.

    Confirm is a second write, so it can fail on its own -- not enough stock in
    that branch, or the connection dropping in between. Claiming success here
    would leave a salesperson believing an order is live.
    """
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), httpx.ConnectError("dropped")]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert answer == erp._not_confirmed("SO-2026-0042")
    assert "SO-2026-0042" in answer
    assert "not" in answer.lower()


def test_a_dead_erp_does_not_leave_the_write_tool_raising(_credentials):
    with patch.object(api_client.httpx, "post", side_effect=httpx.ConnectError("refused")):
        with patch.object(api_client.httpx, "get", side_effect=httpx.ConnectError("refused")):
            assert erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}]) == (
                erp.ORDER_FAILED
            )
