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
        "erp_create_sales_order",
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
