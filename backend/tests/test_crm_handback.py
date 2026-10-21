"""The CRM's "hand back to AI" (task 42.1): `POST /internal/crm/handback`.

The contract is `docs/chatbot-replies.md` section 5 in acuven_crm_demo. What it
is for: an agent in the CRM gives the conversation back, the visitor's next
message is answered by the bot, and the CRM is told at once -- with the same
moment the `handover_changed` event will carry -- that nobody holds it now.

Nothing is sent to the visitor: `whatsapp.send_raw` is wired to fail if it is
ever called. Every signature is computed here from the contract's text.
"""
import hashlib
import hmac
import itertools
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.bots import registry
from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.routers.whatsapp_webhook import dispatch_message
from app.services import crm_events, handover, llm, whatsapp
from app.services.user_store import user_store

client = TestClient(app)

URL = "/internal/crm/handback"
SECRET = "test-send-secret"
NOW = 1_760_000_000
REQUEST_ID = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
PHONE = "60123456789"
BSUID = "MY.4f9a2c7e"
TOKEN = "console-token-for-tests"


@pytest.fixture(autouse=True)
def configured():
    """Signed requests accepted, and any message to the visitor a failure."""
    with patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(internal_crm, "_now", lambda: NOW), \
            patch.object(whatsapp, "send_raw", side_effect=AssertionError("a hand-back sends nothing")) as send:
        yield send


@pytest.fixture
def queue(monkeypatch):
    """The CRM event queue switched on and read back."""
    pushed = []
    fake = MagicMock()
    fake.rpush.side_effect = lambda key, value: pushed.append(json.loads(value))
    crm_events.reset()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: fake)
    with patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "redis_url", "redis://stand-in:6379/16"), \
            patch.object(settings, "crm_events_secret", "test-events-secret"):
        yield pushed
    crm_events.reset()


def _request(**overrides) -> dict:
    request = {
        "request_id": REQUEST_ID,
        "visitor": {"phone": PHONE, "bsuid": None},
        "agent": {"id": "user-9", "name": "Manager Lim"},
    }
    request.update(overrides)
    return request


def _post(request: dict | None = None, *, secret: str = SECRET, body: bytes | None = None, signature=None):
    body = json.dumps(_request() if request is None else request).encode() if body is None else body
    if signature is None:
        signature = "sha256=" + hmac.new(secret.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(URL, content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def _held(identifier: str = PHONE, *, idle_for: float = 0.0):
    """A visitor a person has, last touched `idle_for` seconds ago."""
    profile = user_store.get_or_create(identifier)
    profile.bot_id = "retail"
    user_store.save(profile)
    with patch("app.services.handover.time.time", return_value=time.time() - idle_for):
        handover.begin(user_store.get(identifier))
    return user_store.get(identifier)


def _changes(queue) -> list[dict]:
    return [event for event in queue if event["type"] == "handover_changed"]


# --- ended ----------------------------------------------------------------------


def test_handing_back_a_held_conversation_ends_it_and_says_when(queue):
    _held()
    queue.clear()

    response = _post()

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "ended"
    assert body["handover"]["active"] is False
    assert body["handover"]["expires_at"] is None
    profile = user_store.get(PHONE)
    assert (profile.handover_since, profile.handover_active_at) == (0.0, 0.0)
    (changed,) = _changes(queue)
    assert changed["handover"] == {"active": False, "expires_at": None}
    assert changed["occurred_at"] == body["handover"]["occurred_at"]


def _every_other_clock_runs_on():
    """Every other reading of `time.time` a second later than the last, from
    an hour ahead: any code that reads its own clock instead of using the
    hand-back's moment lands on a different second. (`handover.time.time` is
    `time.time` itself, so this moves it for everyone.)"""
    ticks = itertools.count(time.time() + 3600)
    return patch("app.services.handover.time.time", side_effect=lambda: float(next(ticks)))


def test_the_response_and_the_event_carry_the_same_moment_even_across_a_second(queue):
    _held()
    queue.clear()
    with patch("app.services.crm_send._now", return_value=NOW + 0.999), \
            patch.object(crm_events, "_now", return_value=NOW + 1.0), \
            _every_other_clock_runs_on():
        response = _post()
    (changed,) = _changes(queue)
    assert response.json()["handover"]["occurred_at"] == changed["occurred_at"] == crm_events.utc(NOW)


def test_after_handing_back_the_bot_answers_the_visitor_again(queue):
    _held()
    _post()
    with patch.object(llm, "get_reply", return_value="Happy to help.") as get_reply:
        sent = dispatch_message({"id": "wamid.in.1", "from": PHONE, "type": "text", "text": {"body": "hello?"}})
    get_reply.assert_called_once()
    assert any(message.get("text", {}).get("body") == "Happy to help." for message in sent)


def test_a_takeover_that_had_lapsed_is_still_ended_and_reported(queue):
    """The contract ends whatever has `handover_since` set, lapsed or not, so
    the CRM's stored state is put right either way."""
    _held(idle_for=settings.handover_idle_seconds + 60)
    assert not handover.active(user_store.get(PHONE))
    queue.clear()

    response = _post()

    assert response.json()["result"] == "ended"
    assert len(_changes(queue)) == 1


def test_a_visitor_known_only_by_bsuid_is_handed_back_by_it(queue):
    _held(BSUID)
    queue.clear()
    response = _post(_request(visitor={"phone": None, "bsuid": BSUID}))
    assert response.json()["result"] == "ended"
    assert not user_store.get(BSUID).handover_since


def test_both_keys_are_tried_when_the_number_has_no_takeover(queue):
    user_store.save(user_store.get_or_create(PHONE))
    _held(BSUID)
    queue.clear()
    response = _post(_request(visitor={"phone": PHONE, "bsuid": BSUID}))
    assert response.json()["result"] == "ended"
    assert not user_store.get(BSUID).handover_since


def test_two_records_both_held_are_both_ended_at_one_moment(queue):
    _held(PHONE)
    _held(BSUID)
    queue.clear()
    with _every_other_clock_runs_on():
        response = _post(_request(visitor={"phone": PHONE, "bsuid": BSUID}))
    changes = _changes(queue)
    assert len(changes) == 2
    assert {change["occurred_at"] for change in changes} == {response.json()["handover"]["occurred_at"]}
    assert not user_store.get(PHONE).handover_since
    assert not user_store.get(BSUID).handover_since


# --- not active -----------------------------------------------------------------


def test_handing_back_twice_is_not_active_the_second_time(queue):
    _held()
    _post()
    queue.clear()
    response = _post()
    assert response.status_code == 200
    assert response.json() == {"result": "not_active", "handover": None}
    assert queue == []


def test_a_visitor_nobody_has_is_not_active(queue):
    user_store.save(user_store.get_or_create(PHONE))
    response = _post()
    assert response.json() == {"result": "not_active", "handover": None}
    assert queue == []


def test_a_visitor_not_on_file_is_not_active_and_is_not_filed(queue):
    response = _post()
    assert response.json() == {"result": "not_active", "handover": None}
    assert user_store.get(PHONE) is None
    assert queue == []


# --- the door -------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param(_request(visitor={"phone": None, "bsuid": None}), id="neither phone nor bsuid"),
        pytest.param(_request(visitor={}), id="visitor empty"),
        pytest.param(_request(visitor={"phone": "", "bsuid": ""}), id="both blank"),
        pytest.param(_request(visitor={"phone": "+60123456789", "bsuid": None}), id="phone malformed"),
        pytest.param(_request(visitor={"phone": None, "bsuid": "not a bsuid"}), id="bsuid malformed"),
        pytest.param(_request(request_id="not-a-uuid"), id="request_id not a uuid"),
        pytest.param(_request(agent={"id": "user-9"}), id="agent without name"),
        pytest.param(_request(agent={"id": " ", "name": "Lim"}), id="agent id blank"),
    ],
)
def test_an_invalid_hand_back_is_422_and_changes_nothing(queue, request_body):
    _held()
    queue.clear()
    assert _post(request_body).status_code == 422
    assert handover.active(user_store.get(PHONE))
    assert queue == []


def test_a_bad_signature_is_401_even_on_an_invalid_body():
    body = json.dumps(_request(visitor={"phone": None, "bsuid": None})).encode()
    assert _post(body=body, secret="wrong").status_code == 401


def test_a_signature_over_the_body_alone_is_401():
    body = json.dumps(_request()).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert _post(body=body, signature=signature).status_code == 401


def test_without_a_secret_it_is_503_and_nothing_is_handed_back(queue):
    _held()
    with patch.object(settings, "crm_send_secret", ""):
        assert _post().status_code == 503
    assert handover.active(user_store.get(PHONE))


# --- shared with the console, and switched off ---------------------------------


def test_the_console_no_longer_holds_it_after_a_crm_hand_back(queue):
    _held()
    _post()
    headers = {"X-Console-Token": TOKEN}
    with patch("app.routers.console.settings.console_token", TOKEN):
        held = client.get("/console/handover", headers=headers).json()["customers"]
        reply = client.post("/console/reply", json={"key_id": PHONE, "text": "still me"}, headers=headers)
    assert held == []
    assert reply.status_code == 409


def test_with_the_events_switched_off_it_still_hands_back():
    """No `queue` fixture: CRM_EVENTS_ENABLED stays false."""
    _held()
    response = _post()
    assert response.json()["result"] == "ended"
    assert not user_store.get(PHONE).handover_since


def test_nothing_is_sent_to_the_visitor(configured, queue):
    _held()
    _post()
    configured.assert_not_called()


# Keeps the import honest: the bot registry is what `dispatch_message` answers
# with, and a missing "retail" would make the bot-answers test pass vacuously.
assert registry.get_bot("retail") is not None
