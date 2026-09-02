import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
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


@contextmanager
def credentials():
    """A client that will actually attempt a login.

    Nothing under `backend/` sets CRM_EMAIL, so `settings.crm_email` is "" and
    the client refuses at `_login` before a byte reaches httpx. A test that
    patches httpx and does not do this is asserting against the
    missing-credentials path instead -- review round 1 of task 9.1, P3-1: three
    parametrised transport cases were green for that reason, and would have
    stayed green with a raw httpx error escaping the tool.
    """
    crm_client.reset()
    with patch.object(settings, "crm_email", "demo@acuven.test"):
        with patch.object(settings, "crm_password", "not-a-real-password"):
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
    with credentials():
        with patch.object(api_client.httpx, "post", side_effect=failure) as post:
            assert crm.crm_lookup_customer("David Park") == crm.UNAVAILABLE

    # Without this the test passes whether or not the failure was ever raised.
    assert post.called


def test_missing_credentials_degrade_like_any_other_outage():
    """A forgotten .env line must not crash a demo -- it reads as "cannot check".

    Patched on `settings`, not on the class: `_email` is set in `__init__`, so an
    instance attribute shadows anything put on `CrmClient` and the patch this
    test used to do was inert.
    """
    crm_client.reset()
    with patch.object(settings, "crm_email", ""):
        with patch.object(settings, "crm_password", ""):
            with patch.object(api_client.httpx, "post") as post:
                assert crm.crm_lookup_customer("David Park") == crm.UNAVAILABLE

    # The point of the answer: it was refused here, without a doomed round trip.
    assert post.call_args_list == []


def test_both_tools_are_declared_with_a_schema_the_model_can_read():
    assert [tool.name for tool in crm.TOOLS] == ["crm_lookup_customer", "crm_create_lead"]
    for tool in crm.TOOLS:
        assert tool.input_schema["properties"]
        assert tool.description


# -- crm_create_lead ---------------------------------------------------------

ENQUIRY = "3 units Sony WF-C710N earbuds, COD to Cheras"
VALUE = 986.70

NEW_CONTACT = {"id": "c-9", "name": "Ahmad Faizal", "phone": "+60 12-333 4444"}
NEW_DEAL = {"id": "d-9", "title": ENQUIRY, "amount": 986.70, "status": "lead"}


class FakeCrm:
    """crm_os at the HTTP boundary: answers like the routes do, keeps what was sent.

    The patched methods are the authenticated `get`/`post`, so the returns here are
    already past `_unwrap` -- the same shape the client code actually reads.
    """

    def __init__(self, *, existing=None, deals=None, get_fails=None, post_fails=None):
        self.existing = list(existing or [])
        self.deals = [NEW_DEAL] if deals is None else list(deals)
        self.get_fails = get_fails or {}
        self.post_fails = post_fails or {}
        self.gets = []
        self.posts = []

    def get(self, path, params=None):
        self.gets.append((path, params or {}))
        self._maybe_fail(self.get_fails, path)
        if path == "/api/contacts":
            return {"data": self.existing}
        if path == "/api/deals":
            return self.deals
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, json=None):
        self.posts.append((path, json or {}))
        self._maybe_fail(self.post_fails, path)
        if path == "/api/contacts":
            return NEW_CONTACT
        if path == "/api/deals":
            return NEW_DEAL
        if path.endswith("/activities"):
            return {"id": "a-1"}
        raise AssertionError(f"unexpected POST {path}")

    @staticmethod
    def _maybe_fail(failures, path):
        for fragment, error in failures.items():
            if fragment in path:
                raise error

    @property
    def post_paths(self):
        return [path for path, _ in self.posts]

    def body(self, path):
        """The single body posted to `path`."""
        (body,) = [sent for posted, sent in self.posts if posted == path]
        return body


@contextmanager
def fake_crm(**kwargs):
    fake = FakeCrm(**kwargs)
    with patch.object(crm_client.CrmClient, "get", side_effect=fake.get):
        with patch.object(crm_client.CrmClient, "post", side_effect=fake.post):
            yield fake


def test_a_new_customer_leaves_one_card_on_the_board_not_two():
    """`POST /api/contacts` already creates a deal; a second POST would double it.

    The pipeline is the screen the demo points at. An extra RM 0 card next to the
    real one is not a cosmetic problem there, it is the demo contradicting itself.
    """
    with fake_crm(existing=[]) as fake:
        payload = json.loads(crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE))

    assert fake.post_paths == ["/api/contacts", "/api/deals/d-9/activities"]
    assert fake.body("/api/contacts") == {
        "name": "Ahmad Faizal",
        "phone": "+60 12-333 4444",
        "initial_status": "lead",
        "initial_title": ENQUIRY,
        "initial_amount": VALUE,
    }
    assert payload["deal_id"] == "d-9"
    assert payload["title"] == ENQUIRY
    assert payload["amount"] == VALUE
    assert payload["activity_logged"] is True


def test_the_lead_is_never_flagged_as_gateway_traffic():
    """`demo_scope` hides flagged contacts from the pipeline -- the one place it must show."""
    with fake_crm(existing=[]) as fake:
        crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE)

    assert "is_gateway" not in fake.body("/api/contacts")


def test_a_returning_customer_gets_another_card_not_another_copy_of_themselves():
    """The same phone number runs through this demo again and again."""
    with fake_crm(existing=[TAN]) as fake:
        payload = json.loads(crm.crm_create_lead("Tan Wei Ming", "60173948123", ENQUIRY, VALUE))

    assert "/api/contacts" not in fake.post_paths
    assert fake.body("/api/deals") == {
        "contact_id": "c-1",
        "status": "lead",
        "title": ENQUIRY,
        "amount": VALUE,
    }
    assert payload["contact_id"] == "c-1"


def test_the_note_is_filed_against_the_card_and_marked_whatsapp():
    with fake_crm(existing=[]) as fake:
        crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE)

    body = fake.body("/api/deals/d-9/activities")
    # The route reads the id from the path, but ActivityCreate still requires the
    # field: leaving it out is a 422.
    assert body["deal_id"] == "d-9"
    assert body["type"] == "WhatsApp"
    assert ENQUIRY in body["content"]
    assert "986.70" in body["content"]


def test_the_note_keeps_the_whole_enquiry_the_card_title_had_to_cut():
    long_enquiry = "I want " + "very " * 100 + "many earbuds"

    with fake_crm(existing=[]) as fake:
        crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", long_enquiry, VALUE)

    assert fake.body("/api/contacts")["initial_title"] == long_enquiry[:200]
    assert long_enquiry in fake.body("/api/deals/d-9/activities")["content"]


def test_a_name_too_long_for_the_column_is_trimmed_rather_than_dropped():
    with fake_crm(existing=[]) as fake:
        crm.crm_create_lead("Ahmad " * 40, "+60 12-333 4444", ENQUIRY, VALUE)

    assert len(fake.body("/api/contacts")["name"]) == 100


@pytest.mark.parametrize(
    "phone",
    ["+60 12-333 4444 ext 12345678901234567890", "0123", "call me maybe", ""],
    ids=["longer-than-the-column", "too-few-digits", "not-a-number", "empty"],
)
def test_a_phone_nobody_could_ring_back_is_refused_rather_than_trimmed(phone):
    """A trimmed phone number is a different, wrong number in the field a rep dials."""
    with fake_crm(existing=[]) as fake:
        assert crm.crm_create_lead("Ahmad Faizal", phone, ENQUIRY, VALUE) == crm.BAD_LEAD

    assert fake.posts == []


@pytest.mark.parametrize(
    ("name", "requirement", "amount"),
    [
        ("", ENQUIRY, VALUE),
        ("   ", ENQUIRY, VALUE),
        ("Ahmad Faizal", "", VALUE),
        ("Ahmad Faizal", ENQUIRY, -1),
        ("Ahmad Faizal", ENQUIRY, "not a number"),
        ("Ahmad Faizal", ENQUIRY, float("nan")),
        ("Ahmad Faizal", ENQUIRY, float("inf")),
        ("Ahmad Faizal", ENQUIRY, 10**13),
    ],
    ids=[
        "no-name",
        "blank-name",
        "no-requirement",
        "negative-amount",
        "unparseable-amount",
        "nan-amount",
        "infinite-amount",
        "wider-than-DECIMAL-15-2",
    ],
)
def test_details_that_are_not_a_lead_are_refused_before_anything_is_written(
    name, requirement, amount
):
    with fake_crm(existing=[]) as fake:
        assert crm.crm_create_lead(name, "+60 12-333 4444", requirement, amount) == crm.BAD_LEAD

    assert fake.posts == []


def test_a_write_that_was_refused_says_nothing_was_recorded():
    failed = ApiClientError("422", may_have_landed=False)

    with fake_crm(existing=[], post_fails={"/api/contacts": failed}):
        assert crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE) == crm.LEAD_FAILED


def test_a_write_that_may_have_landed_is_not_reported_as_a_failure():
    """Telling the model it failed is what produces two cards for one customer."""
    unknown = ApiClientError("gateway timeout", may_have_landed=True)

    with fake_crm(existing=[], post_fails={"/api/contacts": unknown}):
        assert crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE) == crm.LEAD_UNKNOWN


def test_a_lookup_that_dies_before_any_write_is_a_clean_failure():
    with fake_crm(get_fails={"/api/contacts": ApiClientError("boom")}) as fake:
        assert crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE) == crm.LEAD_FAILED

    assert fake.posts == []


def test_a_card_already_on_the_board_is_not_called_a_failure_because_the_note_missed():
    with fake_crm(existing=[], post_fails={"/activities": ApiClientError("boom")}):
        payload = json.loads(crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE))

    assert payload["deal_id"] == "d-9"
    assert payload["activity_logged"] is False


def test_losing_the_new_cards_id_still_reports_the_lead_that_exists():
    """The contact and its card are written by then -- LEAD_FAILED would be a lie."""
    with fake_crm(existing=[], get_fails={"/api/deals": ApiClientError("boom")}) as fake:
        payload = json.loads(crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE))

    assert fake.post_paths == ["/api/contacts"]
    assert payload["contact_id"] == "c-9"
    assert payload["deal_id"] is None
    assert payload["activity_logged"] is False


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
def test_a_real_transport_failure_on_a_lead_degrades_instead_of_escaping(failure):
    """Regression twin of the lookup case: raw httpx must not reach the tool runner."""
    with credentials():
        with patch.object(api_client.httpx, "post", side_effect=failure) as post:
            answer = crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE)

    assert answer == crm.LEAD_FAILED
    assert post.called


def test_a_crm_500_is_a_lead_that_was_not_recorded_not_one_in_doubt():
    """Review round 1, P1-1, verified against the live CRM.

    crm_os registers no exception handler, so an error it handled comes back as
    Starlette's `text/plain` "Internal Server Error" -- while `get_db` has
    already rolled the session back. Classified as the gateway's answer it
    became LEAD_UNKNOWN, which tells the model not to save the lead again. There
    was no card, and now there would never be one.
    """
    login = httpx.Response(
        200,
        json={"success": True, "data": {"access_token": "a", "refresh_token": "r"}},
        request=httpx.Request("POST", "https://crm/api/auth/login"),
    )
    rolled_back = httpx.Response(
        500,
        content=b"Internal Server Error",
        headers={"content-type": "text/plain; charset=utf-8"},
        request=httpx.Request("POST", "https://crm/api/contacts"),
    )
    empty_page = httpx.Response(
        200,
        json={"success": True, "data": {"data": [], "total": 0, "page": 1, "page_size": 100}},
        request=httpx.Request("GET", "https://crm/api/contacts"),
    )

    with credentials():
        with patch.object(api_client.httpx, "get", return_value=empty_page):
            with patch.object(api_client.httpx, "post", side_effect=[login, rolled_back]):
                answer = crm.crm_create_lead(
                    "Ahmad Faizal", "+60 12-333 4444", ENQUIRY, VALUE
                )

    assert answer == crm.LEAD_FAILED


def test_an_amount_that_rounds_past_the_column_never_reaches_the_crm():
    """Review round 1, P2-1: DECIMAL(15, 2) rounds first, then range-checks."""
    rounds_over = 9999999999999.998
    assert rounds_over < crm_client.MAX_AMOUNT

    with fake_crm(existing=[]) as fake:
        answer = crm.crm_create_lead("Ahmad Faizal", "+60 12-333 4444", ENQUIRY, rounds_over)

    assert answer == crm.BAD_LEAD
    assert fake.posts == []
