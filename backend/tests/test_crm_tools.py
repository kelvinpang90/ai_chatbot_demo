import json
from unittest.mock import patch

import httpx
import pytest

from app.services import api_client, crm_client
from app.services.api_client import ApiClientError
from app.tools import crm

TAN = {
    "id": "c-1",
    "name": "Tan Wei Ming",
    "company": "Tan Trading Sdn Bhd",
    "phone": "+60 17-394 8123",
    "email": "tan@example.my",
    "total_deal_amount": 12000.0,
    "deal_count": 3,
    "notes": "long note the model does not need",
}

SITI = {
    "id": "c-2",
    "name": "Siti Aminah",
    "company": "Aminah Enterprise",
    "phone": "012-9998888",
    "email": "siti@example.my",
    "total_deal_amount": 0.0,
    "deal_count": 0,
}


@pytest.fixture(autouse=True)
def _fresh_client():
    crm_client.reset()
    yield
    crm_client.reset()


def test_a_name_is_handed_to_the_servers_own_search():
    with patch.object(crm_client.CrmClient, "get", return_value={"data": [TAN]}) as get:
        payload = json.loads(crm.crm_lookup_customer("Tan Wei Ming"))

    assert get.call_args.args[0] == "/api/contacts"
    assert get.call_args.kwargs["params"]["search"] == "Tan Wei Ming"
    assert payload == [
        {
            "contact_id": "c-1",
            "name": "Tan Wei Ming",
            "company": "Tan Trading Sdn Bhd",
            "phone": "+60 17-394 8123",
            "email": "tan@example.my",
            "total_deal_amount": 12000.0,
            "deal_count": 3,
        }
    ]


def test_a_phone_number_is_matched_here_because_the_server_cannot():
    """crm_os `search` covers name and company only -- a phone finds nothing there."""
    with patch.object(crm_client.CrmClient, "get", return_value={"data": [SITI, TAN]}) as get:
        payload = json.loads(crm.crm_lookup_customer("60173948123"))

    # No `search` term went to the server; the filtering happened on our side.
    assert get.call_args.kwargs["params"]["search"] is None
    assert [contact["contact_id"] for contact in payload] == ["c-1"]


@pytest.mark.parametrize(
    "typed",
    ["60173948123", "+60 17-394 8123", "017-3948123", "0173948123", "(017) 394 8123"],
)
def test_the_same_person_is_found_however_the_number_is_written(typed):
    """WhatsApp hands us 60173948123; the CRM holds whatever a salesperson typed."""
    with patch.object(crm_client.CrmClient, "get", return_value={"data": [TAN]}):
        payload = json.loads(crm.crm_lookup_customer(typed))

    assert payload[0]["contact_id"] == "c-1"


def test_a_short_number_is_treated_as_a_name_not_a_phone():
    with patch.object(crm_client.CrmClient, "get", return_value={"data": []}) as get:
        crm.crm_lookup_customer("2024")

    assert get.call_args.kwargs["params"]["search"] == "2024"


def test_the_phone_scan_stops_at_the_end_of_the_book():
    """A short page means there is no next one -- do not keep paging into nothing."""
    with patch.object(crm_client.CrmClient, "get", return_value={"data": [SITI]}) as get:
        assert crm.crm_lookup_customer("60173948123") == crm.NOT_FOUND

    assert get.call_count == 1


def test_the_phone_scan_is_bounded_even_when_every_page_is_full():
    full_page = {"data": [SITI] * crm_client.PAGE_SIZE}

    with patch.object(crm_client.CrmClient, "get", return_value=full_page) as get:
        assert crm.crm_lookup_customer("60173948123") == crm.NOT_FOUND

    assert get.call_count == crm_client.MAX_SCAN_PAGES


def test_an_unknown_customer_says_so_rather_than_returning_nothing():
    with patch.object(crm_client.CrmClient, "get", return_value={"data": []}):
        assert crm.crm_lookup_customer("Nobody At All") == crm.NOT_FOUND


def test_an_unreachable_crm_becomes_an_answer_the_bot_can_relay():
    with patch.object(crm_client.CrmClient, "get", side_effect=ApiClientError("boom")):
        assert crm.crm_lookup_customer("Tan Wei Ming") == crm.UNAVAILABLE


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", "https://crm"), response=httpx.Response(429)
        ),
    ],
    ids=["dead-host", "timeout", "rate-limited"],
)
def test_a_real_transport_failure_degrades_instead_of_escaping(failure):
    """Regression: see the twin in test_erp_tools."""
    with patch.object(api_client.httpx, "post", side_effect=failure):
        assert crm.crm_lookup_customer("David Park") == crm.UNAVAILABLE


def test_missing_credentials_degrade_like_any_other_outage():
    """A forgotten .env line must not crash a demo -- it reads as "cannot check"."""
    crm_client.reset()
    with patch.object(crm_client.CrmClient, "_email", "", create=True):
        with patch.object(crm_client.CrmClient, "_password", "", create=True):
            assert crm.crm_lookup_customer("David Park") == crm.UNAVAILABLE


def test_the_tool_is_declared_with_a_schema_the_model_can_read():
    (tool,) = crm.TOOLS
    assert tool.name == "crm_lookup_customer"
    assert tool.input_schema["properties"]
    assert tool.description
