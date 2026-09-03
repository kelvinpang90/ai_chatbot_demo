import json
from datetime import datetime
from unittest.mock import Mock, patch

import httpx
import pytest

from app.services import api_client, erp_client, outbox, whatsapp_media
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
        "erp_generate_einvoice",
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

    # 3. What Meta was handed is the invoice, and it is a PDF.
    content, mime, filename = _uploaded.call_args.args
    assert content.startswith(b"%PDF-")
    assert (mime, filename) == ("application/pdf", "INV-2026-0007.pdf")

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
