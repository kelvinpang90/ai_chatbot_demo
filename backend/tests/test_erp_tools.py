import io
import json
import re
from datetime import datetime
from unittest.mock import Mock, patch

import httpx
import pytest
from pypdf import PdfReader

from app.services import api_client, erp_client, notify, outbox, whatsapp, whatsapp_media
from app.services.api_client import ApiClientError
from app.services.whatsapp_media import MediaError
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
    catalogue = {"items": [SKU_ROW], "total": 1}
    with patch.object(erp_client.ErpClient, "get", return_value=catalogue) as get:
        payload = json.loads(erp.erp_search_sku("earbuds"))

    assert get.call_args.args[0] == "/api/skus"
    assert get.call_args.kwargs["params"]["search"] == "earbuds"
    assert payload["total_matches"] == 1
    assert payload["products"] == [
        {
            "sku_id": 12,
            "code": "SKU-00012",
            "name": "TWS Earbuds Pro",
            "name_zh": "无线耳机 Pro",
            "unit_price_excl_tax": "89.00",
            "unit_price_incl_tax": "94.34",
            "currency": "MYR",
        }
    ]


def test_the_search_asks_for_as_many_products_as_the_list_can_carry():
    """Five was the ERP's default and it very nearly cost the demo a fan: the
    seed catalogue holds exactly five of them, so the sixth would have gone
    missing with nothing on screen to say it had."""
    with patch.object(erp_client.ErpClient, "get", return_value={"items": [SKU_ROW]}) as get:
        erp.erp_search_sku("fan")

    assert get.call_args.kwargs["params"]["page_size"] == whatsapp.MAX_LIST_ROWS


def test_a_page_of_matches_is_never_passed_off_as_the_whole_catalogue():
    """What the model is told, and the only thing standing between it and
    telling a customer the shop stocks ten fans when it stocks fourteen."""
    page = [{**SKU_ROW, "id": 100 + i, "name": f"Fan {i}"} for i in range(10)]

    with patch.object(erp_client.ErpClient, "get", return_value={"items": page, "total": 14}):
        payload = json.loads(erp.erp_search_sku("fan"))

    assert payload["total_matches"] == 14
    assert len(payload["products"]) == 10


def test_a_count_the_erp_left_out_never_reads_as_fewer_than_arrived():
    """A missing `total` is unknown, not zero -- and certainly not fewer than
    the products sitting in the same response."""
    with patch.object(erp_client.ErpClient, "get", return_value={"items": [SKU_ROW, LITE_SKU_ROW]}):
        assert json.loads(erp.erp_search_sku("earbuds"))["total_matches"] == 2

    with patch.object(erp_client.ErpClient, "get", return_value={"items": [SKU_ROW], "total": 0}):
        assert json.loads(erp.erp_search_sku("earbuds"))["total_matches"] == 1


def test_search_hands_over_both_tax_bases_so_the_quote_matches_the_invoice():
    """The order total and the PDF are tax-inclusive; a lone ex-tax price lies.

    Quoting one number was the old behaviour and it promised RM 89.00 against a
    bill of RM 94.34. Both are here, each named for what it is, so the model can
    read out the one the customer will actually be charged.
    """
    with patch.object(erp_client.ErpClient, "get", return_value={"items": [SKU_ROW]}):
        product = json.loads(erp.erp_search_sku("earbuds"))["products"][0]

    assert product["unit_price_excl_tax"] == "89.00"
    assert product["unit_price_incl_tax"] == "94.34"
    # The ambiguous single field is gone: nothing can read it and get it wrong.
    assert "unit_price" not in product


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


# -- the tappable product list --------------------------------------------------
#
# A search that finds several things ends with the customer typing a product name
# back at us, which on a phone is where orders go to die. The list rides out
# behind the reply through the outbox, so the model writes its answer as it
# always did and cannot forget to offer it or describe it wrongly.

LITE_SKU_ROW = {
    **SKU_ROW,
    "id": 13,
    "code": "SKU-00013",
    "name": "TWS Earbuds Lite",
    "unit_price_incl_tax": "63.60",
}

SOLD_OUT_MATRIX_ROW = {
    "sku_id": 13,
    "sku_code": "SKU-00013",
    "warehouses": [{"warehouse_id": 1, "warehouse_name": "KL Main", "available": "0"}],
}


def _catalogue(skus: list[dict], stock: list[dict] | Exception = (), total: int | None = None):
    """The ERP answering the two routes a search now touches, by route.

    The stock call is a second request for one line of text on a row, so it gets
    its own knob: passing an exception is how the tests below cover an inventory
    route that is down while the catalogue is up. `total` is the catalogue-wide
    count, which is larger than the page whenever there is more to be had.

    Both routes honour the page size they are asked for, as erp_os does. A stub
    that ignored it read the same for a call that asks for five and one that
    asks for ten, and a mutation that quietly halved the stock call's reach sat
    green underneath it.
    """

    def get(path: str, params: dict | None = None, **_kwargs):
        page_size = (params or {}).get("page_size")
        if path.startswith("/api/inventory"):
            if isinstance(stock, Exception):
                raise stock
            return {"rows": list(stock)[:page_size]}
        return {"items": skus[:page_size], "total": len(skus) if total is None else total}

    return patch.object(erp_client.ErpClient, "get", side_effect=get)


def test_several_matches_come_with_a_list_the_customer_can_tap(_outbox):
    with _catalogue([SKU_ROW, LITE_SKU_ROW], stock=[MATRIX_ROW, SOLD_OUT_MATRIX_ROW]):
        payload = json.loads(erp.erp_search_sku("earbuds"))

    # What the model gets is untouched -- it still writes the words itself.
    assert [row["sku_id"] for row in payload["products"]] == [12, 13]

    (message,) = outbox.drain(A_PHONE)
    assert message["type"] == "interactive"
    assert message["interactive"]["type"] == "list"
    (section,) = message["interactive"]["action"]["sections"]
    assert [row["id"] for row in section["rows"]] == ["sku:12", "sku:13"]
    assert section["rows"][0]["title"] == "TWS Earbuds Pro"
    # Price and stock: the tax-inclusive price, the same one the tool tells the
    # model to quote, and what is actually left across the branches (18 + 4).
    assert section["rows"][0]["description"] == "MYR 94.34 · 22 in stock"
    assert section["rows"][1]["description"] == "MYR 63.60 · out of stock"


def test_one_match_is_left_to_the_reply_and_costs_no_second_call(_outbox):
    """A one-row list is a worse way of saying "we have it" than the sentence
    the model is already writing."""
    with _catalogue([SKU_ROW]) as get:
        erp.erp_search_sku("earbuds")

    assert outbox.drain(A_PHONE) == []
    assert [call.args[0] for call in get.call_args_list] == ["/api/skus"]


def test_the_web_demo_is_not_charged_for_a_list_it_cannot_send():
    """No outbox fixture: `routers/chat.py` has no channel for an interactive
    message, so neither the list nor the stock call it needs happens at all."""
    with _catalogue([SKU_ROW, LITE_SKU_ROW]) as get:
        payload = json.loads(erp.erp_search_sku("earbuds"))

    assert len(payload["products"]) == 2  # the model is answered exactly as before
    assert outbox.drain(A_PHONE) == []
    assert [call.args[0] for call in get.call_args_list] == ["/api/skus"]


def test_a_dead_inventory_route_still_leaves_the_products_tappable(_outbox):
    """The stock line is worth a second call; it is not worth the list."""
    with _catalogue([SKU_ROW, LITE_SKU_ROW], stock=ApiClientError("boom")):
        erp.erp_search_sku("earbuds")

    (message,) = outbox.drain(A_PHONE)
    (section,) = message["interactive"]["action"]["sections"]
    assert [row["description"] for row in section["rows"]] == ["MYR 94.34", "MYR 63.60"]


def test_a_product_that_cannot_be_named_or_ordered_is_left_off_the_list(_outbox):
    """The id is what the tap comes back on and the title is what Meta insists
    on. Either missing is a row that would take the whole list down with it."""
    unusable = [{**SKU_ROW, "id": None}, {**LITE_SKU_ROW, "name": "", "code": ""}]

    with _catalogue([SKU_ROW, *unusable], stock=[MATRIX_ROW]):
        erp.erp_search_sku("earbuds")

    assert outbox.drain(A_PHONE) == []  # one usable match left, so no list


def test_the_products_around_an_unusable_one_are_still_offered(_outbox):
    """The point of leaving it out rather than refusing: the other two are fine."""
    with _catalogue([SKU_ROW, {**SKU_ROW, "id": None}, LITE_SKU_ROW], stock=[MATRIX_ROW]):
        erp.erp_search_sku("earbuds")

    (message,) = outbox.drain(A_PHONE)
    (section,) = message["interactive"]["action"]["sections"]
    assert [row["id"] for row in section["rows"]] == ["sku:12", "sku:13"]


def test_more_matches_than_meta_will_carry_says_so_instead_of_hiding_it(_outbox):
    """Ten is the channel's limit, not the size of the catalogue, and a customer
    who cannot see that will believe the shop only stocks these ten.

    The count is the ERP's, not a tally of what arrived -- which is the whole
    point, since what arrived is exactly the ten that fit."""
    page = [{**SKU_ROW, "id": 100 + i, "name": f"Earbuds {i}"} for i in range(10)]

    with _catalogue(page, total=14):
        erp.erp_search_sku("earbuds")

    (message,) = outbox.drain(A_PHONE)
    (section,) = message["interactive"]["action"]["sections"]
    assert len(section["rows"]) == 10
    body = message["interactive"]["body"]["text"]
    assert "10 of 14" in body and "brand or category" in body


def test_every_row_on_a_full_list_carries_its_stock_line(_outbox):
    """The stock call has to reach as far as the search does. Left at the ERP's
    default of five while the search asks for ten, the bottom half of the list
    would be the only rows with no stock on them -- and nothing would say why."""
    page = [{**SKU_ROW, "id": 100 + i, "name": f"Earbuds {i}"} for i in range(8)]
    matrix = [{"sku_id": 100 + i, "warehouses": [{"available": "7"}]} for i in range(8)]

    with _catalogue(page, stock=matrix):
        erp.erp_search_sku("earbuds")

    (message,) = outbox.drain(A_PHONE)
    (section,) = message["interactive"]["action"]["sections"]
    assert [row["description"] for row in section["rows"]] == ["MYR 94.34 · 7 in stock"] * 8


def test_a_page_that_holds_everything_is_not_apologised_for(_outbox):
    """Three rice cookers is three rice cookers. The demo asks this exact
    question, and "showing 3 of 3" would read as though something were missing."""
    with _catalogue([SKU_ROW, LITE_SKU_ROW], stock=[MATRIX_ROW]):
        erp.erp_search_sku("earbuds")

    (message,) = outbox.drain(A_PHONE)
    assert message["interactive"]["body"]["text"] == erp.PRODUCT_LIST_BODY


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
def test_a_real_transport_failure_degrades_instead_of_escaping(failure, erp_credentials):
    """Regression: these three used to escape the tool and blow up the reply.

    The original tests raised ApiClientError -- the type the tool had chosen to
    catch -- so they passed while every failure that actually happens went
    uncaught. Patch httpx itself, not the exception we hoped for.

    `erp_credentials` is what makes that true: without it the client refuses at
    `_login` and none of these three ever reach httpx, which is how this test --
    the one guarding task 8's P1 -- sat green covering nothing until review
    round 2 of task 9.1 measured it.
    """
    with patch.object(api_client.httpx, "post", side_effect=failure) as post:
        assert erp.erp_search_sku("fan") == erp.UNAVAILABLE
        assert erp.erp_get_inventory("fan") == erp.UNAVAILABLE

    assert post.called


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
    assert names == {
        "erp_search_sku",
        "erp_get_inventory",
        "erp_find_customer",
        "erp_create_customer",
        "erp_list_orders",
        "erp_create_sales_order",
        "erp_generate_einvoice",
        "erp_find_order_by_sku",
        "erp_create_credit_note",
    }
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


def _response(
    payload: dict,
    status_code: int = 200,
    text: str = "",
    content_type: str = "application/json",
) -> Mock:
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = text
    response.raise_for_status.return_value = None
    # A real response carries this, and the client reads it to tell an error the
    # application composed from one composed for it by a proxy.
    response.headers = {"content-type": content_type}
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


ADDRESS = "6 Jalan Tasik Selatan 30e, Desa Tasik, Kuala Lumpur 57000"


def test_the_address_the_customer_gave_is_written_onto_the_order(_credentials):
    """The gap the first live order exposed: she typed an address and it vanished.

    It reached the model, which used it to pick a branch, and then went nowhere
    -- so the delivery note said only which warehouse, never where to.
    """
    booked = {**DRAFT_ORDER, "shipping_address": ADDRESS}
    posts = [_response(_LOGIN), _response(booked, 201), _response({**CONFIRMED_ORDER, "shipping_address": ADDRESS})]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            payload = json.loads(
                erp.erp_create_sales_order(
                    3, [{"sku_id": 12, "quantity": 1}], shipping_address=f"  {ADDRESS}  "
                )
            )

    assert post.call_args_list[1].kwargs["json"]["shipping_address"] == ADDRESS
    # Read back from what erp_os stored, so the model can repeat it to the
    # customer without either of them taking it on trust.
    assert payload["shipping_address"] == ADDRESS


def test_an_order_with_no_address_mentioned_does_not_send_an_empty_one(_credentials):
    """Absent and blank are different claims: one is silence, one is "none"."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert "shipping_address" not in post.call_args_list[1].kwargs["json"]


def test_an_address_too_long_for_the_column_is_asked_for_again_not_cut(_credentials):
    """erp_os caps it at 500. Cutting one produces a different, real-looking place.

    Nothing is written: the customer is still in the conversation and can retype
    it, which is exactly what the invoice PDF cannot do when a name overflows.
    """
    with patch.object(api_client.httpx, "post") as post:
        answer = erp.erp_create_sales_order(
            3, [{"sku_id": 12, "quantity": 1}], shipping_address="x" * 501
        )

    assert answer == erp.ADDRESS_TOO_LONG
    assert "shorten it yourself" in answer
    assert post.call_count == 0  # refused before the login, let alone the write


def test_an_address_that_exactly_fills_the_column_is_accepted(_credentials):
    """The guard is off-by-one bait; 500 is allowed, 501 is not."""
    address = "x" * erp_client.MAX_SHIPPING_ADDRESS_CHARS
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            erp.erp_create_sales_order(
                3, [{"sku_id": 12, "quantity": 1}], shipping_address=address
            )

    assert post.call_args_list[1].kwargs["json"]["shipping_address"] == address


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


# -- saying which of the two failures it was ---------------------------------
#
# Review round 1, P2-1: every write failure said "Nothing was booked -- tell the
# customer their order was not placed", including the ones where the request went
# out and no answer came back. A customer told that reorders, and the second
# order is as real as the first.


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("timed out"),
        httpx.WriteTimeout("timed out"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=["read-timeout", "write-timeout", "disconnected"],
)
def test_a_write_that_went_out_unanswered_never_claims_nothing_happened(_credentials, failure):
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), failure]):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert answer == erp.ORDER_UNKNOWN
    assert "Nothing was booked" not in answer
    assert "was not placed" not in answer
    # The instruction that keeps one intent from becoming two orders.
    assert "Do not place it again" in answer


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ConnectTimeout("no route")],
    ids=["refused", "connect-timeout"],
)
def test_a_write_that_never_left_the_process_does_say_nothing_happened(_credentials, failure):
    """The other half of the same call: uncertainty that is not warranted is
    just as bad, because it leaves a live order dangling that never existed."""
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), failure]):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            assert erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}]) == (
                erp.ORDER_FAILED
            )


def test_a_gateway_timeout_on_the_write_is_treated_as_unknown(_credentials):
    """A 504 from the proxy says nothing about what erp_os did with the request."""
    gateway = _response(
        {},
        504,
        text="<html><title>504 Gateway Time-out</title></html>",
        content_type="text/html; charset=UTF-8",
    )
    gateway.json.side_effect = ValueError("not json")

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), gateway]):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            assert erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}]) == (
                erp.ORDER_UNKNOWN
            )


def test_an_error_erp_os_handled_itself_says_the_order_was_not_placed(_credentials):
    """Review round 2, P2-1. A customer_id that is not in the customers table is
    a foreign key violation, which erp_os answers as a 500 carrying its own
    INTERNAL_ERROR envelope -- written after `get_db` rolled the transaction
    back. Nothing was booked, so the bot must be free to look the customer up
    properly and try again."""
    handled = _response({"error_code": "INTERNAL_ERROR"}, 500, text='{"error_code":"INTERNAL_ERROR"}')

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), handled]):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(9999, [{"sku_id": 12, "quantity": 1}])

    assert answer == erp.ORDER_FAILED
    assert answer != erp.ORDER_UNKNOWN


def test_a_slow_catalogue_read_does_not_invent_an_order_that_was_never_posted(_credentials):
    """Review round 2, P1-1. The tool reads /api/skus/{id} to price the line
    before it posts anything. That read timing out used to arrive as "the order
    may exist, do not place it again" -- the sale lost, the retry forbidden, and
    no order anywhere."""
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(api_client.httpx, "get", side_effect=httpx.ReadTimeout("timed out")):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert [c for c in post.call_args_list if "/api/sales-orders" in c.args[0]] == []
    assert answer == erp.ORDER_FAILED


def test_a_refused_confirm_does_not_promise_it_will_clear_by_itself(_credentials):
    """Refused is permanent -- usually not enough stock in that branch."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response({}, 400)]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert answer == erp._not_confirmed("SO-2026-0042")
    assert "REFUSED" in answer


def test_a_confirm_that_timed_out_says_the_order_exists_anyway(_credentials):
    """The order is real either way, so the one thing that must not happen is
    the model creating it a second time."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), httpx.ReadTimeout("timed out")]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
            answer = erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 1}])

    assert answer == erp._confirmation_unknown("SO-2026-0042")
    assert "Do not create the order again" in answer


# -- finding the customer the order is billed to -----------------------------
#
# Review round 1, P1-1: erp_create_sales_order demanded an integer customer_id
# that no tool could produce. crm_lookup_customer answers out of crm_os, whose
# contacts are UUIDs in a different id space, so the model's only option was to
# invent a small integer -- and every small integer is somebody's real account.

CUSTOMER_ROW = {
    "id": 7,
    "code": "CUST-0007",
    "name": "Sunrise Hypermart Sdn Bhd",
    "phone": "+60 17-394 8123",
    "currency": "MYR",
    "credit_limit": "50000.0000",
}


def test_the_tool_set_can_produce_an_erp_customer_id_for_the_order(_credentials):
    """The fix for round 1's P1-1, stated as the things that have to stay true.

    The reviewer's own repro asserts crm_lookup_customer returns an int, which it
    never can -- crm_os keys contacts by UUID and always will. The finding is
    really about whether *some* tool hands the model a value that
    erp_create_sales_order's customer_id will accept.

    Round 2 then pointed out that the first version of this test could not fail:
    it mocked a row with an integer id and asserted the id was an integer. The
    three assertions below fail on the regressions that would actually happen --
    the tool being dropped from TOOLS, the docstring that points the model at it
    being edited away, or the id field being renamed.
    """
    by_name = {tool.name: tool for tool in erp.TOOLS}
    assert "erp_find_customer" in by_name, "the only source of an ERP customer id"

    order = by_name["erp_create_sales_order"]
    assert order.input_schema["properties"]["customer_id"]["type"] == "integer"
    # Having the tool is not enough; the model has to be told to use it, and told
    # what a guessed id costs.
    assert "erp_find_customer" in order.description

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(
            api_client.httpx, "get", return_value=_response({"items": [CUSTOMER_ROW]})
        ):
            found = json.loads(erp.erp_find_customer("Sunrise"))

    # The key the model reads has to be the one the order tool asks for.
    assert order.input_schema["required"] == ["customer_id", "items"]
    assert isinstance(found[0]["customer_id"], int)


def test_a_customer_is_searched_by_name_in_one_call(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(
            api_client.httpx, "get", return_value=_response({"items": [CUSTOMER_ROW]})
        ) as get:
            payload = json.loads(erp.erp_find_customer("Sunrise"))

    assert get.call_count == 1
    assert get.call_args.args[0].endswith("/api/customers")
    assert get.call_args.kwargs["params"]["search"] == "Sunrise"
    assert payload[0]["name"] == "Sunrise Hypermart Sdn Bhd"


@pytest.mark.parametrize(
    "typed", ["+60 17-394 8123", "017-3948123", "60173948123", "0173948123"]
)
def test_a_phone_number_is_matched_locally_because_the_erp_cannot_search_on_it(
    _credentials, typed
):
    """erp_os's ?search= covers code, name, contact_person and email only. The
    phone number is the one identifier a WhatsApp conversation always has, so a
    lookup that could not use it would be no lookup at all."""
    others = [{**CUSTOMER_ROW, "id": 8, "phone": "03-2181 0000"}]
    page = {"items": others + [CUSTOMER_ROW]}

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", return_value=_response(page)) as get:
            payload = json.loads(erp.erp_find_customer(typed))

    # Paging, not searching: a phone number in ?search= would return nothing.
    assert get.call_args.kwargs["params"]["search"] is None
    assert [row["customer_id"] for row in payload] == [7]


def test_an_unknown_customer_tells_the_model_not_to_invent_one(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", return_value=_response({"items": []})):
            answer = erp.erp_find_customer("Nobody At All")

    assert answer == erp.NO_CUSTOMER
    assert "do not invent" in answer.lower()


def test_an_unreachable_erp_does_not_look_like_an_unknown_customer(_credentials):
    """"Not a customer" and "I could not check" must not collapse into one
    answer: the first one invites creating a duplicate account."""
    with patch.object(api_client.httpx, "post", side_effect=httpx.ConnectError("refused")):
        assert erp.erp_find_customer("Sunrise") == erp.UNAVAILABLE


# -- "where is my order" ------------------------------------------------------

ORDER_LIST_ROW = {
    "id": 251,
    "document_no": "SO-2026-00001",
    "status": "FULLY_SHIPPED",
    "customer_id": 1,
    "business_date": "2026-09-02",
    "currency": "MYR",
    "subtotal_excl_tax": "897.0000",
    "total_incl_tax": "986.7000",
}


def test_the_orders_a_customer_asks_about_are_only_ever_their_own(_credentials):
    """The question is "where is my order", and the id decides whose."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(
            api_client.httpx, "get", return_value=_response({"items": [ORDER_LIST_ROW]})
        ) as get:
            payload = json.loads(erp.erp_list_orders(1))

    assert get.call_args.args[0].endswith("/api/sales-orders")
    assert get.call_args.kwargs["params"]["customer_id"] == 1
    assert payload == [
        {
            "order_no": "SO-2026-00001",
            "status": "FULLY_SHIPPED",
            "ordered_on": "2026-09-02",
            "currency": "MYR",
            "total_incl_tax": "986.7000",
        }
    ]


def test_a_customer_with_nothing_on_file_is_told_so_not_shown_somebody_elses(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", return_value=_response({"items": []})):
            assert erp.erp_list_orders(1) == erp.NO_ORDERS


def test_an_unreachable_erp_does_not_look_like_a_customer_with_no_orders(_credentials):
    """"You have no orders" is a claim; "I could not check" is the truth here."""
    with patch.object(api_client.httpx, "post", side_effect=httpx.ConnectError("refused")):
        assert erp.erp_list_orders(1) == erp.UNAVAILABLE


# -- issuing the e-Invoice ----------------------------------------------------
#
# Same approach as the order tests: httpx is driven, not ErpClient, so a wrong
# route or a payload erp_os would reject fails here rather than on the phone.
# The chain is four writes long -- ship, generate, submit, upload -- and each one
# of them can fail on its own with the ones before it already done.

SO_LIST_ROW = {"id": 77, "document_no": "SO-2026-0042", "status": "CONFIRMED"}
SO_DETAIL = {
    **CONFIRMED_ORDER,
    "lines": [
        {
            "id": 501,
            "sku_code": "SKU-00012",
            "sku_name": "TWS Earbuds Pro",
            "qty_ordered": "3.0000",
            "qty_shipped": "0.0000",
        }
    ],
}
SHIPPED_SO = {
    **SO_DETAIL,
    "status": "FULLY_SHIPPED",
    "lines": [{**SO_DETAIL["lines"][0], "qty_shipped": "3.0000"}],
}

DRAFT_INVOICE = {
    "id": 9,
    "document_no": "INV-2026-0007",
    "status": "DRAFT",
    "sales_order_no": "SO-2026-0042",
    "customer_name": "Tan Ah Kau",
    "currency": "MYR",
    "business_date": "2026-09-03",
    "subtotal_excl_tax": "897.0000",
    "tax_amount": "89.7000",
    "total_incl_tax": "986.7000",
    "uin": None,
    "lines": [
        {
            "description": "TWS Earbuds Pro",
            "qty": "3.0000",
            "unit_price_excl_tax": "299.0000",
            "line_total_excl_tax": "897.0000",
            "line_total_incl_tax": "986.7000",
        }
    ],
}
VALIDATED_INVOICE = {**DRAFT_INVOICE, "status": "VALIDATED", "uin": "MY-UIN-8891234"}

MEDIA_ID = "meta-media-777"
A_PHONE = "60123456789"


@pytest.fixture
def _outbox():
    """A WhatsApp conversation, which is the only channel with room for a file."""
    outbox.begin()
    yield


@pytest.fixture
def _uploaded():
    """Meta accepting the PDF. What was handed over is asserted where it matters."""
    with patch.object(whatsapp_media, "upload_media", return_value=MEDIA_ID) as upload:
        yield upload


NO_INVOICE_YET = {"items": []}


def _invoice_gets(order: dict = SO_DETAIL, invoiced: dict | None = None) -> list:
    """The three reads before anything is written: find the customer's order by
    number, load it in full, then ask whether it has been billed already."""
    reads = [_response({"items": [SO_LIST_ROW]}), _response(order)]
    if invoiced is None:
        return reads + [_response(NO_INVOICE_YET)]
    return reads + [_response({"items": [{"id": invoiced["id"]}]}), _response(invoiced)]


def test_the_order_is_shipped_invoiced_submitted_and_the_pdf_goes_to_the_customer(
    _credentials, _outbox, _uploaded
):
    posts = [
        _response(_LOGIN),
        _response({"id": 300, "document_no": "DO-2026-0031"}, 201),
        _response(DRAFT_INVOICE, 201),
        _response(VALIDATED_INVOICE),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()) as get:
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    # 1. The order was found under this customer, not by number alone.
    lookup = get.call_args_list[0]
    assert lookup.args[0].endswith("/api/sales-orders")
    assert lookup.kwargs["params"] == {
        "search": "SO-2026-0042",
        "customer_id": 3,
        "page_size": erp_client.DEFAULT_RESULT_LIMIT,
    }
    assert get.call_args_list[1].args[0].endswith("/api/sales-orders/77")
    billed_already = get.call_args_list[2]
    assert billed_already.args[0].endswith("/api/invoices")
    assert billed_already.kwargs["params"]["sales_order_id"] == 77

    # 2. Three writes, in the order erp_os's state machine demands.
    ship, generate, submit = post.call_args_list[1:]
    assert ship.args[0].endswith("/api/delivery-orders")
    assert ship.kwargs["json"]["sales_order_id"] == 77
    assert ship.kwargs["json"]["lines"] == [{"sales_order_line_id": 501, "qty_shipped": "3.0000"}]
    assert generate.args[0].endswith("/api/invoices/generate-from-so/77")
    assert submit.args[0].endswith("/api/invoices/9/submit")

    # 3. What Meta was handed is this invoice, read back out of the PDF rather
    #    than trusted from its magic number -- round 2, P3-1: this assertion was
    #    `content.startswith(b"%PDF-")`, and a fixture that had drifted off
    #    `line_total_excl_tax` rendered a blank AMOUNT column past all four of
    #    the tests that run this document.
    content, mime, filename = _uploaded.call_args.args
    assert (mime, filename) == ("application/pdf", "INV-2026-0007.pdf")
    document = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "INV-2026-0007" in document
    # The line row itself, not just the numbers somewhere on the page: 897.00 is
    # also the subtotal, so `"897.00" in document` passes with the AMOUNT column
    # blank -- which is the mutation this assertion has to survive.
    (row,) = [ln for ln in document.splitlines() if ln.startswith("TWS Earbuds Pro")]
    assert re.findall(r"[\d,]+\.\d\d", row) == ["299.00", "897.00"]

    # 4. It is queued as a document addressed to the customer, named so they can
    #    quote the number back.
    (message,) = outbox.drain(A_PHONE)
    assert message["to"] == A_PHONE
    assert message["type"] == "document"
    assert message["document"]["id"] == MEDIA_ID
    assert message["document"]["filename"] == "INV-2026-0007.pdf"
    assert "INV-2026-0007" in message["document"]["caption"]

    # 5. What the model is told, including the number that has to match the ERP.
    assert payload == {
        "invoice_no": "INV-2026-0007",
        "order_no": "SO-2026-0042",
        "status": "VALIDATED",
        "lhdn_uin": "MY-UIN-8891234",
        "currency": "MYR",
        "total_incl_tax": "986.7000",
        "pdf_sent": True,
    }


def test_an_order_that_already_shipped_is_not_shipped_a_second_time(
    _credentials, _outbox, _uploaded
):
    """The tool is documented as safe to call again; this is the step that makes
    it true, because a second delivery order would move stock that already left."""
    posts = [_response(_LOGIN), _response(DRAFT_INVOICE, 201), _response(VALIDATED_INVOICE)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SHIPPED_SO)):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert not any("/api/delivery-orders" in call.args[0] for call in post.call_args_list)
    assert payload["pdf_sent"] is True


def test_an_invoice_that_is_no_longer_a_draft_is_not_submitted_again(
    _credentials, _outbox, _uploaded
):
    """erp_os returns the existing invoice for a second generate call, and
    submitting one that is already VALIDATED is a 400 that would fail the tool."""
    posts = [_response(_LOGIN), _response(VALIDATED_INVOICE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SHIPPED_SO)):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert not any("/submit" in call.args[0] for call in post.call_args_list)
    assert payload["status"] == "VALIDATED"


def test_an_order_that_was_billed_before_is_sent_its_existing_invoice(
    _credentials, _outbox, _uploaded
):
    """Half the orders in the demo database are seeded INVOICED with a real
    invoice attached, and a customer asking about one of those wants the document
    that exists. Raising a second one would bill them twice; refusing would be a
    lie about a document sitting in the ERP."""
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(
            api_client.httpx,
            "get",
            side_effect=_invoice_gets(
                {**SO_DETAIL, "status": "INVOICED"}, invoiced=VALIDATED_INVOICE
            ),
        ):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    # Nothing was shipped, generated or submitted -- only the login went out.
    assert post.call_count == 1
    assert payload["invoice_no"] == "INV-2026-0007"
    assert payload["pdf_sent"] is True
    (message,) = outbox.drain(A_PHONE)
    assert message["document"]["filename"] == "INV-2026-0007.pdf"


def test_a_second_call_after_a_failed_delivery_does_not_bill_the_customer_twice(
    _credentials, _outbox, _uploaded
):
    """The tool tells the model it is safe to call again. This is the call that
    follows, with the shipment and the invoice from the first one already done."""
    posts = [_response(_LOGIN), _response(VALIDATED_INVOICE)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SHIPPED_SO, invoiced=DRAFT_INVOICE)
        ):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    # The invoice found on file was still a draft, so it is submitted -- but it is
    # not raised again, and the order is not shipped again.
    assert post.call_args_list[1].args[0].endswith("/api/invoices/9/submit")
    assert not any("generate-from-so" in call.args[0] for call in post.call_args_list)
    assert not any("/api/delivery-orders" in call.args[0] for call in post.call_args_list)
    assert payload["pdf_sent"] is True


def test_an_order_marked_billed_with_no_invoice_on_file_does_not_raise_another(
    _credentials, _outbox
):
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets({**SO_DETAIL, "status": "PAID"})
        ):
            answer = erp.erp_generate_einvoice("SO-2026-0042", 3)

    assert "PAID" in answer
    assert "Do not raise a new one" in answer
    assert post.call_count == 1


def test_a_void_invoice_is_not_sent_as_the_customers_bill(_credentials, _outbox, _uploaded):
    """Round 2, P3-2. An invoice LHDN rejected or the office withdrew is still
    attached to the order, and sending it would hand the customer a document the
    ERP no longer stands behind. Raising a replacement is not this tool's call
    either -- a credit note and a new invoice is somebody's decision."""
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(
            api_client.httpx,
            "get",
            side_effect=_invoice_gets(
                {**SO_DETAIL, "status": "INVOICED"},
                invoiced={**VALIDATED_INVOICE, "status": "CANCELLED"},
            ),
        ):
            answer = erp.erp_generate_einvoice("SO-2026-0042", 3)

    assert "cancelled" in answer
    assert "Do not raise a new one" in answer
    assert post.call_count == 1
    assert _uploaded.call_count == 0
    assert outbox.drain(A_PHONE) == []


def test_an_order_number_that_belongs_to_nobody_here_writes_nothing(_credentials, _outbox):
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(api_client.httpx, "get", return_value=_response({"items": []})):
            answer = erp.erp_generate_einvoice("SO-9999-9999", 3)

    assert answer == erp.NO_SUCH_ORDER
    assert post.call_count == 1  # the login, and nothing else
    assert outbox.drain(A_PHONE) == []


def test_a_number_the_search_only_partly_matched_is_not_taken_as_the_order(_credentials, _outbox):
    """`?search=` is a LIKE over document_no and remarks, so it answers with
    orders that merely contain the text. Shipping one of those would move a
    different order's stock and send this customer somebody else's invoice."""
    neighbour = {"id": 78, "document_no": "SO-2026-00420", "status": "CONFIRMED"}

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(api_client.httpx, "get", return_value=_response({"items": [neighbour]})):
            assert erp.erp_generate_einvoice("SO-2026-0042", 3) == erp.NO_SUCH_ORDER

    assert post.call_count == 1


def test_the_number_is_matched_the_way_the_erp_matched_it_not_more_strictly(
    _credentials, _outbox, _uploaded
):
    """Round 1, P3-1. erp_os's `?search=` is a case-insensitive LIKE, so a
    compare stricter than the ERP's own throws away a row the ERP already found
    and tells the customer their order does not exist. The number is trimmed on
    the way out too, or the LIKE hunts for a leading space no document number has.
    """
    posts = [_response(_LOGIN), _response({"id": 300}, 201), _response(VALIDATED_INVOICE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()) as get:
            payload = json.loads(erp.erp_generate_einvoice("  so-2026-0042 ", 3))

    assert get.call_args_list[0].kwargs["params"]["search"] == "SO-2026-0042".lower()
    assert payload["invoice_no"] == "INV-2026-0007"
    # What comes back is the ERP's spelling, which is what is on the document.
    assert payload["order_no"] == "SO-2026-0042"


def test_a_neighbouring_number_is_still_refused_however_it_is_typed(_credentials, _outbox):
    """The loosening above must not reach as far as a different order."""
    neighbour = {"id": 78, "document_no": "SO-2026-00420", "status": "CONFIRMED"}

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(api_client.httpx, "get", return_value=_response({"items": [neighbour]})):
            assert erp.erp_generate_einvoice("so-2026-0042", 3) == erp.NO_SUCH_ORDER

    assert post.call_count == 1


@pytest.mark.parametrize(
    "status, expected",
    [("DRAFT", "has not been confirmed"), ("CANCELLED", "was cancelled")],
)
def test_an_order_nobody_can_bill_for_is_refused_before_anything_ships(
    _credentials, _outbox, status, expected
):
    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN)]) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets({**SO_DETAIL, "status": status})
        ):
            answer = erp.erp_generate_einvoice("SO-2026-0042", 3)

    assert expected in answer
    assert "SO-2026-0042" in answer
    assert post.call_count == 1


def test_a_shipment_the_erp_refused_stops_before_an_invoice_is_asked_for(_credentials, _outbox):
    """Not enough stock in the branch: erp_os answered for itself, so nothing
    moved and there is nothing to bill."""
    refused = _response({}, 400, text='{"detail":"Insufficient stock in KL Main."}')

    with patch.object(api_client.httpx, "post", side_effect=[_response(_LOGIN), refused]) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            assert erp.erp_generate_einvoice("SO-2026-0042", 3) == erp.INVOICE_FAILED

    assert post.call_count == 2  # login, the refused shipment, and no generate


def test_a_shipment_that_went_out_unanswered_lets_the_invoice_settle_it(
    _credentials, _outbox, _uploaded
):
    """A delivery that timed out may well have landed. Giving up would leave that
    unresolved; asking for the invoice answers it either way, and cannot ship
    anything a second time."""
    posts = [
        _response(_LOGIN),
        httpx.ReadTimeout("no answer"),
        _response(DRAFT_INVOICE, 201),
        _response(VALIDATED_INVOICE),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert any("/api/invoices/generate-from-so/77" in call.args[0] for call in post.call_args_list)
    assert payload["pdf_sent"] is True


def test_a_shipment_that_never_left_this_process_is_not_treated_as_maybe_shipped(
    _credentials, _outbox
):
    posts = [_response(_LOGIN), httpx.ConnectError("refused")]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            assert erp.erp_generate_einvoice("SO-2026-0042", 3) == erp.INVOICE_FAILED

    assert post.call_count == 2


def test_a_refused_invoice_says_the_order_itself_is_untouched(_credentials, _outbox):
    """The customer's order is the thing they care about, and it is still placed."""
    refused = _response({}, 400, text='{"detail":"SO_NOT_INVOICEABLE"}')
    posts = [_response(_LOGIN), _response({"id": 300}, 201), refused]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            answer = erp.erp_generate_einvoice("SO-2026-0042", 3)

    assert answer == erp.INVOICE_FAILED
    assert "still placed" in answer
    # A retry cannot duplicate anything here, so the advice is to take it.
    assert "safe" in answer


def test_an_invoice_myinvois_would_not_validate_is_still_sent_to_the_customer(
    _credentials, _outbox, _uploaded
):
    """A real invoice with a pending UIN beats no invoice at all."""
    posts = [
        _response(_LOGIN),
        _response({"id": 300}, 201),
        _response(DRAFT_INVOICE, 201),
        httpx.ConnectError("myinvois down"),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert payload["status"] == "DRAFT"
    assert payload["lhdn_uin"] is None
    assert payload["pdf_sent"] is True
    assert len(outbox.drain(A_PHONE)) == 1


def test_a_pdf_that_could_not_be_delivered_is_not_reported_as_a_failed_invoice(
    _credentials, _outbox
):
    """The invoice exists in the ERP by this point. Calling it a failure would be
    untrue and would send the model back to issue a second one."""
    posts = [
        _response(_LOGIN),
        _response({"id": 300}, 201),
        _response(DRAFT_INVOICE, 201),
        _response(VALIDATED_INVOICE),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            with patch.object(
                whatsapp_media, "upload_media", side_effect=MediaError("meta refused")
            ):
                payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert payload["invoice_no"] == "INV-2026-0007"
    assert payload["pdf_sent"] is False
    assert payload["note"] == erp.PDF_NOT_SENT
    assert outbox.drain(A_PHONE) == []


def test_a_channel_that_cannot_carry_a_file_says_so_without_uploading_one(
    _credentials, _uploaded
):
    """The web demo has no way to send a document. The bot must not promise one."""
    posts = [
        _response(_LOGIN),
        _response({"id": 300}, 201),
        _response(DRAFT_INVOICE, 201),
        _response(VALIDATED_INVOICE),
    ]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets()):
            payload = json.loads(erp.erp_generate_einvoice("SO-2026-0042", 3))

    assert payload["pdf_sent"] is False
    assert payload["note"] == erp.PDF_NOT_SENT
    assert _uploaded.call_count == 0  # nothing sent to Meta to be thrown away


def test_a_dead_erp_does_not_leave_the_invoice_tool_raising(_credentials, _outbox):
    with patch.object(api_client.httpx, "post", side_effect=httpx.ConnectError("refused")):
        with patch.object(api_client.httpx, "get", side_effect=httpx.ConnectError("refused")):
            assert erp.erp_generate_einvoice("SO-2026-0042", 3) == erp.UNAVAILABLE


def test_the_invoice_tool_is_declared_with_a_schema_the_model_can_read():
    (tool,) = [t for t in erp.TOOLS if t.name == "erp_generate_einvoice"]
    schema = tool.input_schema

    assert set(schema["required"]) == {"order_no", "customer_id"}
    # The customer id is what scopes the lookup, so the model has to be told
    # where it comes from rather than left to produce one.
    assert "erp_find_customer" in schema["properties"]["customer_id"]["description"]
    assert "erp_create_sales_order" in schema["properties"]["order_no"]["description"]


# -- opening an account for a walk-in ------------------------------------------
#
# Until task 32 the demo's customers were picked off a menu, and the flagship one
# was an existing ERP trade account, so the order and the e-Invoice always had a
# customer_id to hang on. A real phone number never does: it belongs to somebody
# the ERP has never heard of, which left the two most convincing tools in the set
# unreachable from a real phone. This is the tool that closes that gap.

WALK_IN_ROW = {
    "id": 77,
    "code": "WA-60173948123",
    "name": "Kelvin Pang",
    "phone": "+60 17-394 8123",
    "currency": "MYR",
}


def test_opening_an_account_returns_an_id_the_order_tool_can_use():
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[]):
        with patch.object(erp_client.ErpClient, "post", return_value=WALK_IN_ROW) as post:
            payload = json.loads(erp.erp_create_customer("Kelvin Pang", "+60 17-394 8123"))

    assert post.call_args.args[0] == "/api/customers"
    assert payload["created"] is True
    assert payload["customer_id"] == 77


def test_the_account_carries_the_number_that_will_have_to_find_it_again():
    """`find_customers` scans the phone column. An account opened without one is
    invisible to the next conversation from that number."""
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[]):
        with patch.object(erp_client.ErpClient, "post", return_value=WALK_IN_ROW) as post:
            erp.erp_create_customer("Kelvin Pang", "+60 17-394 8123", address="Unit 140, Reed")

    body = post.call_args.kwargs["json"]
    assert body["phone"] == "+60 17-394 8123"
    assert body["code"].startswith("WA-60173948123-")
    assert body["address_line1"] == "Unit 140, Reed"


def test_an_individual_is_opened_as_b2c_so_their_invoice_passes_lhdn():
    """erp_os pre-validates against LHDN's rules, where a B2B buyer with no TIN
    fails and a B2C buyer without one passes. Someone who named no company is an
    individual, and saying so keeps their e-Invoice clean."""
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[]):
        with patch.object(erp_client.ErpClient, "post", return_value=WALK_IN_ROW) as post:
            erp.erp_create_customer("Kelvin Pang", "60173948123")

    body = post.call_args.kwargs["json"]
    assert body["customer_type"] == "B2C"
    assert body["name"] == "Kelvin Pang"
    assert "tin" not in body


def test_a_company_is_opened_as_b2b_with_the_person_as_the_contact():
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[]):
        with patch.object(erp_client.ErpClient, "post", return_value=WALK_IN_ROW) as post:
            erp.erp_create_customer(
                "Kelvin Pang", "60173948123", company="Acuven Technology", tin="C1234567890"
            )

    body = post.call_args.kwargs["json"]
    assert body["customer_type"] == "B2B"
    assert body["name"] == "Acuven Technology"
    assert body["contact_person"] == "Kelvin Pang"
    assert body["tin"] == "C1234567890"


def test_somebody_who_already_has_an_account_is_not_given_a_second_one():
    """Two accounts for one number splits their orders across two records and
    leaves a salesperson looking at half a history."""
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[WALK_IN_ROW]):
        with patch.object(erp_client.ErpClient, "post") as post:
            payload = json.loads(erp.erp_create_customer("Kelvin Pang", "017-3948123"))

    post.assert_not_called()
    assert payload["already_had_an_account"] is True
    assert payload["customer_id"] == 77


def test_no_phone_number_means_asking_rather_than_opening_a_findable_nothing():
    with patch.object(erp_client.ErpClient, "post") as post:
        assert erp.erp_create_customer("Kelvin Pang", "") == erp.NEEDS_A_PHONE_NUMBER

    post.assert_not_called()


def test_a_refused_write_and_an_unanswered_one_are_told_apart():
    """The same distinction the order tool makes: told "it failed", the model
    tries again, and a second attempt opens a duplicate account."""
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[]):
        with patch.object(erp_client.ErpClient, "post", side_effect=ApiClientError("refused")):
            assert erp.erp_create_customer("K", "60173948123") == erp.ACCOUNT_FAILED

        unanswered = ApiClientError("timed out", may_have_landed=True)
        with patch.object(erp_client.ErpClient, "post", side_effect=unanswered):
            assert erp.erp_create_customer("K", "60173948123") == erp.ACCOUNT_UNKNOWN


def test_a_cleaned_up_number_can_open_an_account_again():
    """erp_os counts deleted rows when checking a code is unique, "to prevent
    reuse" -- so a code that is only the phone number is burned the first time
    task 34's cleanup runs, and the demo number is the same one every time."""
    first = erp._customer_code("60173948123")
    with patch.object(erp, "datetime") as clock:
        clock.now.return_value.strftime.return_value = "2609060900"
        later = erp._customer_code("60173948123")

    assert first != later
    assert first.startswith("WA-60173948123-") and later.startswith("WA-60173948123-")
    assert len(later) <= 32  # erp_os caps the column there


def test_one_customer_still_cannot_hold_two_accounts():
    """The guarantee moved from the code to the lookup, which is where it
    belongs: it asks whether this person has an account, not whether this exact
    string was ever issued."""
    with patch.object(erp_client.ErpClient, "find_customers", return_value=[WALK_IN_ROW]):
        with patch.object(erp_client.ErpClient, "post") as post:
            erp.erp_create_customer("Kelvin Pang", "60173948123")

    post.assert_not_called()


# -- returns (task 16) ---------------------------------------------------------
#
# Two tools with one hard fact behind them: erp_os indexes nothing by product,
# and it credits invoice lines rather than orders. So the first tool opens the
# customer's orders one at a time to find the product, and the second walks
# order -> invoice -> invoice line before it writes anything. What these guard is
# that neither walk ever crosses into somebody else's account, and that the one
# write is the right line at the right quantity.

FINAL_INVOICE = {
    **DRAFT_INVOICE,
    "status": "FINAL",
    "uin": "MY-UIN-8891234",
    # Not decoration: erp_os refuses to credit an invoice with no branch on it,
    # because a return has to put the stock back somewhere.
    "warehouse_id": 1,
    "warehouse_name": "KL Main",
    "lines": [
        {
            **DRAFT_INVOICE["lines"][0],
            "id": 8801,
            "sku_id": 12,
            "sku_code": "SKU-00012",
            "sku_name": "TWS Earbuds Pro",
        }
    ],
}
CREDIT_NOTE = {
    "id": 41,
    "document_no": "CN-2026-0003",
    "status": "DRAFT",
    "invoice_id": 9,
    "invoice_no": "INV-2026-0007",
    "customer_name": "Tan Ah Kau",
    "currency": "MYR",
    "total_incl_tax": "986.7000",
    "lines": [{"id": 61, "invoice_line_id": 8801, "qty": "3.0000"}],
}

OTHER_SO_DETAIL = {
    **SO_DETAIL,
    "id": 78,
    "document_no": "SO-2026-0041",
    "lines": [
        {
            "id": 502,
            "sku_code": "SKU-00099",
            "sku_name": "Desk Fan 16 inch",
            "qty_ordered": "1.0000",
            "qty_shipped": "1.0000",
        }
    ],
}


def _orders_page(*rows: dict) -> dict:
    return {"items": [{"id": row["id"], "document_no": row["document_no"]} for row in rows]}


def _sku_search_gets(*orders: dict) -> list:
    """One list call for the customer's orders, then one call per order opened."""
    return [_response(_orders_page(*orders))] + [_response(order) for order in orders]


def test_the_order_a_returned_item_came_on_is_found_by_its_code(_credentials):
    gets = _sku_search_gets(OTHER_SO_DETAIL, SO_DETAIL)

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=gets) as get:
            payload = json.loads(erp.erp_find_order_by_sku(3, "SKU-00012"))

    assert get.call_args_list[0].args[0].endswith("/api/sales-orders")
    assert get.call_args_list[0].kwargs["params"]["customer_id"] == 3
    assert [row["order_no"] for row in payload] == ["SO-2026-0042"]
    assert payload[0]["item"] == {
        "code": "SKU-00012",
        "name": "TWS Earbuds Pro",
        "qty": "3.0000",
        "line_total_incl_tax": None,
    }


def test_a_product_named_the_way_a_customer_says_it_is_matched_too(_credentials):
    """The photo gives the bot a code; the customer gives it words. Both have to
    find the same order, or scene 2a only works when the label is readable."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=_sku_search_gets(SO_DETAIL)):
            payload = json.loads(erp.erp_find_order_by_sku(3, "earbuds pro"))

    assert [row["order_no"] for row in payload] == ["SO-2026-0042"]


def test_a_name_that_only_half_matches_is_not_that_product(_credentials):
    """Every word has to be there. "sony earbuds" must not come back with
    somebody else's earbuds because they share the second word."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=_sku_search_gets(SO_DETAIL)):
            answer = erp.erp_find_order_by_sku(3, "sony earbuds")

    assert answer == erp.NO_ORDER_WITH_THAT_SKU


def test_a_query_too_short_to_mean_anything_matches_nothing(_credentials):
    """A single letter is in most catalogues. Matching on it would hand the
    customer their most recent order and call it a search result."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=_sku_search_gets(SO_DETAIL)):
            answer = erp.erp_find_order_by_sku(3, "e")

    assert answer == erp.NO_ORDER_WITH_THAT_SKU


def test_the_search_stops_once_it_has_enough_orders_to_offer(_credentials):
    """One HTTP call per order opened, and a customer who buys the same thing
    monthly has a lot of them. Three is enough to ask "which one?"."""
    many = [{**SO_DETAIL, "id": 70 + n, "document_no": f"SO-2026-00{40 + n}"} for n in range(6)]

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=_sku_search_gets(*many)) as get:
            payload = json.loads(erp.erp_find_order_by_sku(3, "SKU-00012"))

    assert len(payload) == erp.MAX_SKU_ORDER_MATCHES
    # The list call plus one per order opened, and it stopped opening them.
    assert len(get.call_args_list) == 1 + erp.MAX_SKU_ORDER_MATCHES


def test_an_order_that_could_not_be_read_is_never_reported_as_not_bought(_credentials):
    """The one answer this tool must not give by accident: telling a customer
    holding the thing that they never bought it. A half-read search says so."""
    gets = [
        _response(_orders_page(SO_DETAIL, OTHER_SO_DETAIL)),
        httpx.ConnectError("erp is down"),
    ]

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", side_effect=gets):
            answer = erp.erp_find_order_by_sku(3, "SKU-99999")

    assert answer == erp.UNAVAILABLE


def test_a_customer_with_no_orders_at_all_is_told_that_not_shown_a_search(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)):
        with patch.object(api_client.httpx, "get", return_value=_response({"items": []})):
            assert erp.erp_find_order_by_sku(3, "SKU-00012") == erp.NO_ORDERS


def test_the_refund_note_is_raised_against_the_invoice_line_not_the_order_line(_credentials):
    """The acceptance criterion, and the thing that made this task bigger than it
    reads: erp_os credits `invoice_line_id`, so order line 501 is not what goes
    in the payload -- invoice line 8801 is."""
    posts = [_response(_LOGIN), _response(CREDIT_NOTE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            payload = json.loads(
                erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012", "case arrived cracked")
            )

    write = post.call_args_list[1]
    assert write.args[0].endswith("/api/credit-notes")
    body = write.kwargs["json"]
    assert body["invoice_id"] == 9
    assert body["reason"] == "RETURN"
    assert body["reason_description"] == "case arrived cracked"
    assert body["lines"] == [{"invoice_line_id": 8801, "qty": "3.0"}]
    assert payload["credit_note_no"] == "CN-2026-0003"
    assert payload["invoice_no"] == "INV-2026-0007"
    assert payload["item"]["qty_returned"] == 3.0


def test_only_what_is_coming_back_is_credited_when_the_customer_says_a_number(_credentials):
    posts = [_response(_LOGIN), _response(CREDIT_NOTE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012", "one is faulty", quantity=1)

    assert post.call_args_list[1].kwargs["json"]["lines"] == [
        {"invoice_line_id": 8801, "qty": "1.0"}
    ]


def test_more_than_was_invoiced_is_refused_before_anything_is_written(_credentials):
    """Caught here rather than at the far end, while the customer is still
    reading. erp_os has the last word -- it also knows what earlier credit notes
    took -- but a return of five against an invoice for three is answerable now."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012", "", quantity=5)

    assert answer == erp.BAD_RETURN_QUANTITY
    assert len(post.call_args_list) == 1  # the login, and nothing else


def test_an_order_that_was_never_invoiced_has_nothing_to_credit(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL)):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert "not been invoiced" in answer
    assert len(post.call_args_list) == 1


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED"])
def test_an_invoice_still_going_through_lhdn_is_not_credited_yet(_credentials, status):
    """erp_os credits VALIDATED and FINAL only. Sending it anything else is a 422
    the customer waits for, so the answer is composed here instead."""
    invoice = {**FINAL_INVOICE, "status": status}

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, invoice)):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert status in answer and "validated" in answer
    assert len(post.call_args_list) == 1


@pytest.mark.parametrize("status", ["REJECTED", "CANCELLED"])
def test_a_void_invoice_is_not_something_to_refund_against(_credentials, status):
    """Different from the one above in what the customer is told: a bill on its
    way through LHDN clears by itself, and one LHDN threw out never will."""
    invoice = {**FINAL_INVOICE, "status": status}

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, invoice)):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert status.lower() in answer and "colleague" in answer
    assert len(post.call_args_list) == 1


def test_a_product_that_was_not_on_that_invoice_is_refused(_credentials):
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00099")

    assert "SKU-00099" in answer
    assert len(post.call_args_list) == 1


def test_an_order_number_that_belongs_to_nobody_here_refunds_nothing(_credentials):
    """Same guard the invoice tool has, for a write that moves money the other
    way: the order is looked up under this customer, so a number the model
    invented finds nothing rather than refunding a stranger."""
    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(api_client.httpx, "get", return_value=_response({"items": []})):
            answer = erp.erp_create_credit_note("SO-9999-9999", 3, "SKU-00012")

    assert answer == erp.NO_SUCH_ORDER_TO_CREDIT
    assert len(post.call_args_list) == 1


def test_a_refund_that_may_have_landed_never_tells_the_model_to_try_again(_credentials):
    """The one place where "try again" is the wrong instinct. A second credit
    note for the same goods is a second refund, and the model is told to stop."""
    posts = [_response(_LOGIN), httpx.ReadTimeout("no answer")]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert answer == erp.CREDIT_UNKNOWN
    assert "Do not try again" in answer
    assert answer != erp.CREDIT_FAILED


def test_a_refund_erp_os_refused_says_so_without_suggesting_a_smaller_one(_credentials):
    posts = [_response(_LOGIN), _response({"message": "already credited"}, 422)]

    with patch.object(api_client.httpx, "post", side_effect=posts):
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert answer == erp.CREDIT_FAILED
    assert "different quantity" in answer


def test_the_refund_note_is_left_as_a_draft_rather_than_submitted(_credentials):
    """Unlike the invoice one step upstream. erp_os will not cancel a submitted
    credit note, so submitting would make every rehearsal permanent."""
    posts = [_response(_LOGIN), _response(CREDIT_NOTE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            payload = json.loads(erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012"))

    assert len(post.call_args_list) == 2  # the login and the credit note, nothing after
    assert not any("submit" in call.args[0] for call in post.call_args_list)
    assert payload["status"] == "DRAFT"


def test_a_reason_nobody_gave_is_not_invented_into_the_document(_credentials):
    posts = [_response(_LOGIN), _response(CREDIT_NOTE, 201)]

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012", reason="   ")

    assert "reason_description" not in post.call_args_list[1].kwargs["json"]


def test_a_reason_longer_than_the_column_is_cut_rather_than_losing_the_refund(_credentials):
    posts = [_response(_LOGIN), _response(CREDIT_NOTE, 201)]
    essay = "x" * (erp_client.MAX_CREDIT_REASON_CHARS + 200)

    with patch.object(api_client.httpx, "post", side_effect=posts) as post:
        with patch.object(
            api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, FINAL_INVOICE)
        ):
            erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012", reason=essay)

    written = post.call_args_list[1].kwargs["json"]["reason_description"]
    assert len(written) == erp_client.MAX_CREDIT_REASON_CHARS


def test_an_invoice_with_no_branch_on_it_says_so_rather_than_already_refunded(_credentials):
    """Found on the live ERP on 2026-09-11, and the reason this check exists:
    every seeded invoice has no warehouse, erp_os refuses to credit one, and
    without this the customer is told their goods "have already been credited".
    Only invoices this bot raised itself carry a branch -- which is a fact about
    which orders scene 2a can be run against, recorded in tasks/todo.md."""
    homeless = {**FINAL_INVOICE, "warehouse_id": None, "warehouse_name": None}

    with patch.object(api_client.httpx, "post", return_value=_response(_LOGIN)) as post:
        with patch.object(api_client.httpx, "get", side_effect=_invoice_gets(SO_DETAIL, homeless)):
            answer = erp.erp_create_credit_note("SO-2026-0042", 3, "SKU-00012")

    assert "no branch recorded" in answer
    assert "already" not in answer
    assert len(post.call_args_list) == 1  # the login, and nothing written


# -- the phone buzzing afterwards (task 19) ------------------------------------


@pytest.fixture
def _push_queue():
    """A WhatsApp turn. Without one a tool has nowhere to leave a follow-up."""
    notify.begin()
    yield
    notify.close()


def test_a_confirmed_order_leaves_the_phone_buzzing_afterwards(_credentials, _push_queue):
    """Scene 3's opening move: nobody asked for this message. What the tool does
    is queue it -- sending it here would put it in front of the reply that
    explains the order."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]
    queued = []

    with patch.object(notify, "add", side_effect=queued.append) as add:
        with patch.object(api_client.httpx, "post", side_effect=posts):
            with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
                erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}])

    assert add.call_count == 1
    push = queued[0]
    assert push.delay_seconds == erp.settings.push_delay_seconds
    assert CONFIRMED_ORDER["document_no"] in push.text
    # Three languages, because it is a line the model did not write -- the same
    # rule test_whatsapp_webhook.py pins for every other canned message.
    assert len(push.text.split(" / ")) == 3


def test_the_template_parameters_are_in_the_order_the_document_promised(
    _credentials, _push_queue
):
    """docs/whatsapp-templates.md says {{1}} is the name, {{2}} the order number,
    {{3}} the total. Swap two and nothing here fails -- the customer just reads
    their total where the order number should be."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]
    queued = []

    with patch.object(notify, "add", side_effect=queued.append):
        with patch.object(api_client.httpx, "post", side_effect=posts):
            with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
                erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}])

    template = queued[0].template
    assert template.name == notify.ORDER_CONFIRMED
    name, order_no, total = template.params
    assert name == CONFIRMED_ORDER["customer_name"]
    assert order_no == CONFIRMED_ORDER["document_no"]
    assert CONFIRMED_ORDER["total_incl_tax"] in total


def test_an_order_the_erp_refused_to_confirm_promises_nothing(_credentials, _push_queue):
    """The push says the order is confirmed. An order sitting as an unconfirmed
    draft would have the customer's phone say so anyway, half a minute later."""
    posts = [
        _response(_LOGIN),
        _response(DRAFT_ORDER, 201),
        _response({"message": "insufficient stock"}, 422),
    ]

    with patch.object(notify, "add") as add:
        with patch.object(api_client.httpx, "post", side_effect=posts):
            with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
                erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}])

    add.assert_not_called()


def test_the_web_chat_is_never_promised_a_message_it_cannot_receive(_credentials):
    """No queue open means no phone. A bot that says "I'll message you when it
    ships" to somebody on a laptop has promised them nothing."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]

    assert notify.available() is False
    with patch.object(notify, "add") as add:
        with patch.object(api_client.httpx, "post", side_effect=posts):
            with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
                payload = json.loads(
                    erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}])
                )

    # Asked before queuing rather than left to `notify.add` to refuse: the tool
    # is the thing that knows a follow-up was never on the table, and a warning
    # logged on every web order would be noise about a case that is normal.
    add.assert_not_called()
    # The order itself is unaffected -- only the follow-up is.
    assert payload["order_no"] == CONFIRMED_ORDER["document_no"]


def test_the_push_quotes_a_total_the_way_a_shop_would(_credentials, _push_queue):
    """Seen on a real phone on 2026-09-12: the bot said "RM 328.90" and then its
    own push said "MYR 986.7000" a minute later -- the one line in the
    conversation that read like a database."""
    posts = [_response(_LOGIN), _response(DRAFT_ORDER, 201), _response(CONFIRMED_ORDER)]
    queued = []

    with patch.object(notify, "add", side_effect=queued.append):
        with patch.object(api_client.httpx, "post", side_effect=posts):
            with patch.object(api_client.httpx, "get", return_value=_response(SKU_DETAIL)):
                erp.erp_create_sales_order(3, [{"sku_id": 12, "quantity": 3}])

    assert "RM 986.70" in queued[0].text
    assert "MYR" not in queued[0].text
    assert "986.7000" not in queued[0].text


def test_a_total_in_some_other_currency_keeps_its_own_name():
    """RM is what Malaysia writes. Anything else is left as the ERP called it
    rather than relabelled into a currency it is not."""
    assert erp._money("SGD", "1234.5") == "SGD 1,234.50"
    assert erp._money("MYR", "986.7000") == "RM 986.70"
    assert erp._money("myr", 1321.744) == "RM 1,321.74"


def test_a_total_that_is_not_a_number_does_not_take_the_push_down():
    """The push is worth sending without a figure in it; a traceback on a timer
    thread half a minute after the order is not."""
    assert erp._money("MYR", None) == ""
    assert erp._money("MYR", "not money") == ""
