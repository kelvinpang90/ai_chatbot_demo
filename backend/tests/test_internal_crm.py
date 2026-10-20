"""The door of `POST /internal/crm/send` (task 41.1): who gets in, and in what order
they are turned away.

The contract is `docs/chatbot-replies.md` section 5 in acuven_crm_demo. Every
signature here is computed by the test itself from that text -- never by the
module under test -- so a wrong rule in the module cannot agree with itself.

What lies past the door (`crm_send.send`, task 41.2) is stubbed here: these
tests are about who reaches it, and with what. `test_crm_send.py` is the inside.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm

client = TestClient(app)

URL = "/internal/crm/send"
SECRET = "test-send-secret"
OLD_SECRET = "test-send-secret-before-rotation"
NOW = 1_760_000_000


def _sign(secret: str, timestamp, body: bytes) -> str:
    """The contract's signature: HMAC-SHA256 over `<timestamp>.<raw body>`."""
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()


def _request(**overrides) -> dict:
    request = {
        "request_id": "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b",
        "visitor": {"phone": "60123456789", "bsuid": None},
        "text": "Hello from the CRM",
        "agent": {"id": "user-7", "name": "Mei"},
    }
    request.update(overrides)
    return request


def _body(request: dict | None = None) -> bytes:
    return json.dumps(_request() if request is None else request).encode("utf-8")


def _post(body: bytes, *, secret: str = SECRET, timestamp=NOW, headers: dict | None = None):
    if headers is None:
        headers = {
            "X-Acuven-Timestamp": str(timestamp),
            "X-Acuven-Signature": _sign(secret, timestamp, body),
        }
    return client.post(URL, content=body, headers={"Content-Type": "application/json", **headers})


REACHED = {"result": "reached the inside"}


@pytest.fixture(autouse=True)
def inside():
    """A configured chatbot with its clock stopped at NOW, and the send stubbed."""
    stub = MagicMock(return_value=(200, REACHED))
    with patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(internal_crm, "_now", lambda: NOW), \
            patch.object(internal_crm.crm_send, "send", stub):
        yield stub


# --- no secret configured -------------------------------------------------------


def test_nothing_turned_away_reaches_the_inside(inside):
    """Every refusal below is at the door: none of them may have sent anything."""
    _post(_body(), secret="wrong")
    _post(b"not json at all")
    with patch.object(settings, "crm_send_secret", ""):
        _post(_body())
    inside.assert_not_called()


def test_without_a_secret_everything_is_refused_with_503():
    with patch.object(settings, "crm_send_secret", ""):
        response = _post(_body())
    assert response.status_code == 503


def test_without_a_secret_even_a_correct_signature_is_503():
    """Unconfigured is checked before anything else: a request signed with the
    old key alone must not get in because the main one was forgotten."""
    with patch.object(settings, "crm_send_secret", ""), \
            patch.object(settings, "crm_send_secret_previous", OLD_SECRET):
        response = _post(_body(), secret=OLD_SECRET)
    assert response.status_code == 503


# --- the signature --------------------------------------------------------------


def test_a_correctly_signed_valid_request_gets_through(inside):
    response = _post(_body())
    assert response.status_code == 200
    assert response.json() == REACHED
    inside.assert_called_once_with(
        request_id="3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b",
        phone="60123456789",
        bsuid=None,
        text="Hello from the CRM",
        agent_id="user-7",
        agent_name="Mei",
    )


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no headers"),
        pytest.param({"X-Acuven-Timestamp": str(NOW)}, id="no signature"),
        pytest.param({"X-Acuven-Signature": _sign(SECRET, NOW, _body())}, id="no timestamp"),
        pytest.param(
            {"X-Acuven-Timestamp": "1760000000.0", "X-Acuven-Signature": _sign(SECRET, "1760000000.0", _body())},
            id="timestamp not an integer",
        ),
        pytest.param(
            {"X-Acuven-Timestamp": "abc", "X-Acuven-Signature": _sign(SECRET, "abc", _body())},
            id="timestamp not a number",
        ),
        pytest.param(
            {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": _sign(SECRET, NOW, _body()).removeprefix("sha256=")},
            id="signature without sha256=",
        ),
        pytest.param(
            {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": _sign("some-other-secret", NOW, _body())},
            id="wrong secret",
        ),
        pytest.param(
            # As bytes: httpx will not encode a non-ASCII str header itself.
            {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": ("sha256=" + "é" * 64).encode("latin-1")},
            id="signature not ascii",
        ),
    ],
)
def test_a_bad_or_missing_signature_is_401(headers):
    assert _post(_body(), headers=headers).status_code == 401


@pytest.mark.parametrize("offset", [-300, 300])
def test_a_timestamp_300_seconds_off_is_still_accepted(offset):
    assert _post(_body(), timestamp=NOW + offset).status_code == 200


@pytest.mark.parametrize("offset", [-301, 301])
def test_a_timestamp_more_than_300_seconds_off_is_401(offset):
    assert _post(_body(), timestamp=NOW + offset).status_code == 401


def test_the_previous_secret_is_accepted_while_it_is_configured():
    with patch.object(settings, "crm_send_secret_previous", OLD_SECRET):
        assert _post(_body(), secret=OLD_SECRET).status_code == 200
        assert _post(_body(), secret=SECRET).status_code == 200


def test_the_previous_secret_is_refused_once_it_is_not_configured():
    assert _post(_body(), secret=OLD_SECRET).status_code == 401


def test_a_body_changed_by_one_byte_after_signing_is_401():
    signed = _body()
    sent = signed.replace(b"Hello", b"Hellp")
    headers = {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": _sign(SECRET, NOW, signed)}
    assert _post(sent, headers=headers).status_code == 401


def test_a_signature_over_the_body_alone_is_401():
    """The timestamp is part of what is signed; without it a captured request
    could be replayed forever with a fresh timestamp."""
    body = _body()
    body_only = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": body_only}
    assert _post(body, headers=headers).status_code == 401


# --- the request body -----------------------------------------------------------


def test_a_signed_body_that_is_not_json_is_422():
    assert _post(b"not json at all").status_code == 422


def _with_visitor(**visitor) -> dict:
    return _request(visitor={"phone": "60123456789", "bsuid": None, **visitor})


def _with_agent(**agent) -> dict:
    return _request(agent=agent)


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param(_request(request_id="not-a-uuid"), id="request_id not a uuid"),
        pytest.param({k: v for k, v in _request().items() if k != "request_id"}, id="request_id missing"),
        pytest.param(_with_visitor(phone=""), id="phone empty"),
        pytest.param(_with_visitor(phone=None), id="phone null"),
        pytest.param(_with_visitor(phone="+60123456789"), id="phone with plus"),
        pytest.param(_with_visitor(phone="6012345"), id="phone 7 digits"),
        pytest.param(_with_visitor(phone="6012345678901234"), id="phone 16 digits"),
        pytest.param(_with_visitor(phone=60123456789), id="phone a number"),
        pytest.param(_with_visitor(phone="٦٠١٢٣٤٥٦٧٨٩"), id="phone non-ascii digits"),
        pytest.param(_with_visitor(bsuid="not a bsuid"), id="bsuid malformed"),
        pytest.param(_request(visitor=None), id="visitor missing"),
        pytest.param(_request(text="   \n\t "), id="text only whitespace"),
        pytest.param(_request(text="x" * 4097), id="text 4097 chars"),
        pytest.param(_request(text=None), id="text null"),
        pytest.param(_with_agent(name="Mei"), id="agent without id"),
        pytest.param(_with_agent(id="user-7"), id="agent without name"),
        pytest.param(_with_agent(id="  ", name="Mei"), id="agent id blank"),
        pytest.param(_with_agent(id="user-7", name=""), id="agent name empty"),
    ],
)
def test_an_invalid_signed_body_is_422(request_body):
    assert _post(_body(request_body)).status_code == 422


def test_a_bad_signature_on_an_invalid_body_is_401_not_422():
    """Nobody unsigned learns what a valid body looks like."""
    body = _body(_request(request_id="not-a-uuid"))
    headers = {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": _sign("wrong", NOW, body)}
    assert _post(body, headers=headers).status_code == 401


def test_text_of_exactly_4096_characters_after_trimming_is_accepted():
    assert _post(_body(_request(text="  " + "x" * 4096 + "\n"))).status_code == 200


def test_a_visitor_with_a_bsuid_and_extra_keys_is_accepted():
    request_body = _with_visitor(bsuid="MY.4f9a2c7e")
    request_body["something_new"] = "ignored"
    assert _post(_body(request_body)).status_code == 200


def test_the_parsed_request_is_normalised():
    """What the inside keys and sends on: the uuid in its canonical form, the text trimmed."""
    parsed = internal_crm.SendRequest.model_validate(
        _request(request_id="3F2B8C1E-5D4A-4E6F-9A7B-1C2D3E4F5A6B", text="  hi  ")
    )
    assert str(parsed.request_id) == "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"
    assert parsed.text == "hi"


def test_the_inside_gets_the_normalised_request(inside):
    request_body = _request(
        request_id="3F2B8C1E-5D4A-4E6F-9A7B-1C2D3E4F5A6B",
        visitor={"phone": "60123456789", "bsuid": " MY.4f9a2c7e "},
        text="  hi  ",
    )
    _post(_body(request_body))
    assert inside.call_args.kwargs == {
        "request_id": "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b",
        "phone": "60123456789",
        "bsuid": "MY.4f9a2c7e",
        "text": "hi",
        "agent_id": "user-7",
        "agent_name": "Mei",
    }
