"""What a signed request to `POST /internal/crm/send` does once it is through the
door (task 41.2): the idempotency key, the send, and which answer the CRM gets.

The contract is `docs/chatbot-replies.md` section 5 in acuven_crm_demo. What it
is all for: however many times the CRM retries one `request_id`, the visitor
gets the message at most once -- and the CRM can tell "Meta refused it" (safe to
drop) from "nobody knows" (keep it, retry it).

Meta is stubbed one layer down, at the `httpx.post` that `whatsapp.send_raw`
makes, so `send_raw`'s own handling of a refusal is part of what is tested. The
key's Redis is a fake that keeps values and expiries; a real `redis:7` ran the
same cases by hand (see the task record).
"""
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.services import audit, crm_events, crm_send, handover
from app.services.user_store import user_store
from app.session_store import session_store

client = TestClient(app)

URL = "/internal/crm/send"
SECRET = "test-send-secret"
NOW = 1_760_000_000
REQUEST_ID = "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"
PHONE = "60123456789"
KEY = f"chat:crm_send:{REQUEST_ID}"


class FakeRedis:
    """`get`, `set` with `nx` / `ex`, `delete`: what the key needs. Breakable."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.calls: list[tuple] = []
        self.broken: set[str] = set()

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name in self.broken:
            raise ConnectionError(f"redis {name} failed")

    def get(self, key):
        self._call("get", key)
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        self._call("set", key, value)
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        self._call("delete", key)
        self.ttls.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    crm_send.reset()
    monkeypatch.setattr(crm_send, "_client_factory", lambda url: fake)
    with patch.object(settings, "redis_url", "redis://stand-in:6379/16"):
        yield fake
    crm_send.reset()


@pytest.fixture(autouse=True)
def configured():
    session_store.reset()
    with patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(internal_crm, "_now", lambda: NOW):
        yield
    session_store.reset()


def _meta_answers(status: int, body: dict | None = None):
    """Meta answering one send, as `httpx.post` would hand it back."""
    def answer(url, **kwargs):
        return httpx.Response(status, json=body or {}, request=httpx.Request("POST", url))
    return answer


ACCEPTED = _meta_answers(200, {"messaging_product": "whatsapp", "messages": [{"id": "wamid.SENT1"}]})
UNDELIVERABLE = _meta_answers(
    400,
    {"error": {"message": "(#131026) Message undeliverable", "type": "OAuthException", "code": 131026,
               "error_data": {"messaging_product": "whatsapp", "details": "Message undeliverable"},
               "fbtrace_id": "Az1"}},
)


def _meta(side_effect):
    return patch("app.services.whatsapp.httpx.post", side_effect=side_effect)


def _post(text: str = "Hello from the CRM", request_id: str = REQUEST_ID, bsuid: str | None = None):
    body = json.dumps({
        "request_id": request_id,
        "visitor": {"phone": PHONE, "bsuid": bsuid},
        "text": text,
        "agent": {"id": "user-7", "name": "Mei"},
    }).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(URL, content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def _stored(redis) -> dict | None:
    raw = redis.values.get(KEY)
    return json.loads(raw) if raw is not None else None


# --- sent -----------------------------------------------------------------------


def test_a_reply_is_sent_to_the_number_and_remembered_for_48_hours(redis):
    with _meta(ACCEPTED) as meta:
        response = _post("  Hello from the CRM  ")

    assert response.status_code == 200
    assert response.json()["result"] == "sent"
    assert response.json()["wa_message_id"] == "wamid.SENT1"
    payload = meta.call_args.kwargs["json"]
    assert payload["to"] == PHONE
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "Hello from the CRM"
    assert _stored(redis) == {"wa_message_id": "wamid.SENT1"}
    assert redis.ttls[KEY] == 48 * 60 * 60


def test_the_placeholder_is_taken_with_nx_and_a_120_second_expiry_before_meta_is_called(redis):
    seen = {}

    def accept(url, **kwargs):
        seen["key"] = _stored(redis)
        seen["ttl"] = redis.ttls.get(KEY)
        return ACCEPTED(url, **kwargs)

    with _meta(accept):
        assert _post().status_code == 200
    assert seen == {"key": {"state": "sending"}, "ttl": 120}


def test_the_same_request_twice_reaches_the_visitor_once(redis):
    with _meta(ACCEPTED) as meta:
        first = _post()
        second = _post()

    assert first.json()["result"] == "sent"
    assert second.status_code == 200
    assert second.json() == {"result": "duplicate", "wa_message_id": "wamid.SENT1", "handover": None}
    assert meta.call_count == 1


def test_the_key_is_the_canonical_uuid_however_the_crm_cases_it(redis):
    with _meta(ACCEPTED) as meta:
        _post(request_id=REQUEST_ID.upper())
        again = _post(request_id=REQUEST_ID)
    assert KEY in redis.values
    assert again.json()["result"] == "duplicate"
    assert meta.call_count == 1


def test_a_send_does_not_count_towards_the_daily_limit(redis):
    with _meta(ACCEPTED):
        _post()
    assert session_store._daily_counts == {}


# --- in progress ----------------------------------------------------------------


def test_while_the_first_attempt_is_still_sending_a_retry_is_409_and_sends_nothing(redis):
    redis.values[KEY] = json.dumps({"state": "sending"})
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 409
    assert response.json() == {"result": "in_progress"}
    meta.assert_not_called()


def test_the_key_is_taken_in_one_atomic_step(redis):
    """No read-then-write: two copies of one request arriving together would
    both read nothing and both send. NX is the whole check."""
    with _meta(ACCEPTED):
        _post()
    takes = [call for call in redis.calls if call[0] == "set" and "sending" in call[2]]
    assert len(takes) == 1
    assert redis.calls[0][0] == "set"


def test_a_key_that_expires_between_the_nx_and_the_read_is_still_409(redis):
    """NX failed, so somebody had it; gone a moment later means a placeholder
    just ran out. Not ours to send this time -- the next retry will be."""
    redis.values[KEY] = json.dumps({"state": "sending"})
    real_get = redis.get

    def get(key):
        redis.values.pop(key, None)  # expires right here
        return real_get(key)

    redis.get = get
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 409
    meta.assert_not_called()


def test_a_key_that_holds_something_unreadable_is_409_and_sends_nothing(redis):
    redis.values[KEY] = "not json"
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 409
    meta.assert_not_called()


# --- Meta refused ---------------------------------------------------------------


def test_a_refusal_from_meta_is_502_with_its_code_and_title_and_frees_the_key(redis):
    with _meta(UNDELIVERABLE):
        response = _post()

    assert response.status_code == 502
    assert response.json() == {
        "result": "rejected", "error_code": 131026, "error_title": "(#131026) Message undeliverable",
    }
    assert KEY not in redis.values


def test_after_a_refusal_the_same_request_really_is_sent_again(redis):
    """Refused means not sent, so a retry with the same key must try again."""
    with _meta(UNDELIVERABLE):
        _post()
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.json()["result"] == "sent"
    assert meta.call_count == 1


def test_a_refusal_prefers_metas_user_facing_title(redis):
    body = {"error": {"message": "technical", "code": 131047, "error_user_title": "Re-engagement message"}}
    with _meta(_meta_answers(400, body)):
        response = _post()
    assert response.json() == {"result": "rejected", "error_code": 131047, "error_title": "Re-engagement message"}


@pytest.mark.parametrize(
    "body",
    [pytest.param({}, id="no error object"), pytest.param({"error": "a string"}, id="error not an object")],
)
def test_a_refusal_without_a_readable_error_still_is_502(redis, body):
    with _meta(_meta_answers(403, body)):
        response = _post()
    assert response.status_code == 502
    assert response.json() == {"result": "rejected", "error_code": None, "error_title": None}


def test_a_refusal_title_is_cut_to_300_characters(redis):
    with _meta(_meta_answers(400, {"error": {"code": 100, "message": "x" * 1000}})):
        response = _post()
    assert response.json()["error_title"] == "x" * 300


def test_a_refusal_that_cannot_free_the_key_still_answers_502(redis, caplog):
    redis.broken.add("delete")
    with _meta(UNDELIVERABLE):
        response = _post()
    assert response.status_code == 502
    assert any(record.levelname == "ERROR" for record in caplog.records)


# --- nobody knows ---------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(_meta_answers(500, {"error": {"code": 1, "message": "unknown"}}), id="meta 500"),
        pytest.param(_meta_answers(503), id="meta 503"),
        pytest.param(httpx.ReadTimeout("read timed out"), id="read timeout"),
        pytest.param(httpx.ConnectTimeout("connect timed out"), id="connect timeout"),
        pytest.param(httpx.ConnectError("connection refused"), id="connect error"),
        pytest.param(httpx.RemoteProtocolError("connection dropped"), id="dropped mid-response"),
    ],
)
def test_when_it_is_not_known_whether_meta_took_it_the_answer_is_504_and_the_key_stays(redis, outcome):
    with _meta(outcome):
        response = _post()
    assert response.status_code == 504
    assert response.json() == {"result": "unknown"}
    assert _stored(redis) == {"state": "sending"}
    assert redis.ttls[KEY] == 120


def test_after_an_unknown_outcome_a_quick_retry_is_409_and_sends_nothing(redis):
    with _meta(_meta_answers(500)):
        _post()
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 409
    meta.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [pytest.param({"messages": []}, id="no messages"), pytest.param({"ok": True}, id="unexpected shape")],
)
def test_a_200_from_meta_without_a_message_id_is_504_and_the_key_stays(redis, body, caplog):
    with _meta(_meta_answers(200, body)):
        response = _post()
    assert response.status_code == 504
    assert _stored(redis) == {"state": "sending"}
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_a_200_from_meta_that_is_not_json_is_504(redis):
    def not_json(url, **kwargs):
        return httpx.Response(200, content=b"<html>", request=httpx.Request("POST", url))

    with _meta(not_json):
        assert _post().status_code == 504


def test_failing_before_anything_reaches_meta_frees_the_key_and_is_500(redis):
    with _meta(ACCEPTED) as meta, \
            patch.object(crm_send.whatsapp, "build_text_message", side_effect=ValueError("bug")):
        response = _post()
    assert response.status_code == 500
    assert KEY not in redis.values
    meta.assert_not_called()


# --- Redis ----------------------------------------------------------------------


@pytest.mark.parametrize("operation", ["get", "set"])
def test_without_redis_nothing_is_sent_and_the_answer_is_503(redis, operation):
    """No key, no promise that a retry will not send twice: refuse cleanly
    instead, which the CRM reads as "not sent" and lets the agent send again.
    (`get` is only reached once the key turns out to be taken.)"""
    redis.values[KEY] = json.dumps({"state": "sending"})
    redis.broken.add(operation)
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 503
    assert response.json() == {"result": "unavailable"}
    meta.assert_not_called()


def test_without_a_redis_url_nothing_is_sent_and_the_answer_is_503(redis):
    with patch.object(settings, "redis_url", ""), _meta(ACCEPTED) as meta:
        response = _post()
    assert response.status_code == 503
    meta.assert_not_called()


def test_a_send_that_cannot_record_its_id_still_answers_sent(redis, caplog):
    """It went out; saying otherwise would make the CRM drop a message the
    visitor has. The placeholder expires on its own."""
    real_set = redis.set

    def set_(key, value, nx=False, ex=None):
        if "wa_message_id" in value:
            raise ConnectionError("redis set failed")
        return real_set(key, value, nx=nx, ex=ex)

    redis.set = set_
    with _meta(ACCEPTED):
        response = _post()
    assert response.status_code == 200
    assert response.json()["result"] == "sent"
    assert any(record.levelname == "ERROR" for record in caplog.records)


# --- what the logs may say ------------------------------------------------------


def test_the_logs_carry_the_request_id_but_not_the_text_or_the_whole_number(redis, caplog):
    with _meta(UNDELIVERABLE):
        _post("a private message")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert REQUEST_ID in logged
    assert "a private message" not in logged
    assert PHONE not in logged


# === after the send (task 41.3) ===================================================
#
# Contract section 5 step 4, in this order: the key holds Meta's id, the
# `agent_reply` event is queued, the takeover starts or is renewed (its
# `handover_changed` and the response carrying the same moment), then the
# history and the audit log. Nothing after the send may turn "sent" into
# anything else.

BSUID = "MY.4f9a2c7e"
TOKEN = "console-token-for-tests"


@pytest.fixture
def queue(redis, monkeypatch):
    """The CRM event queue switched on, writing into the same call log as the key's Redis."""
    events_redis = MagicMock()
    events_redis.rpush.side_effect = lambda key, value: redis.calls.append(("rpush", key, value))
    crm_events.reset()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: events_redis)
    with patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "crm_events_secret", "test-events-secret"):
        yield lambda: [json.loads(call[2]) for call in redis.calls if call[0] == "rpush"]
    crm_events.reset()


@pytest.fixture
def audit_log():
    """An audit store that keeps what it is given."""
    store = MagicMock()
    store.enabled = True
    store.record_message.return_value = 1
    with patch.object(audit, "audit_store", store):
        yield store


def _sent(**kwargs):
    with _meta(ACCEPTED):
        return _post(**kwargs)


def _expiry(moment: float) -> str:
    return crm_events.utc(moment + settings.handover_idle_seconds)


def test_a_first_reply_to_a_visitor_never_seen_files_them_and_takes_over(redis, queue):
    response = _sent()

    profile = user_store.get(PHONE)
    assert profile is not None and profile.phone == PHONE
    assert handover.active(profile)
    taken = profile.handover_active_at
    assert response.json() == {
        "result": "sent",
        "wa_message_id": "wamid.SENT1",
        "handover": {"active": True, "expires_at": _expiry(taken), "occurred_at": crm_events.utc(taken)},
    }


def test_the_response_and_the_event_carry_the_same_moment_even_across_a_second(redis, queue):
    """Two clocks read a moment apart can straddle a second; the contract wants
    one value. The takeover's own clock reads x.999, the queue's x+1."""
    with patch("app.services.handover.time.time", return_value=NOW + 0.999), \
            patch.object(crm_events, "_now", return_value=NOW + 1.0):
        response = _sent()

    (changed,) = [event for event in queue() if event["type"] == "handover_changed"]
    assert response.json()["handover"]["occurred_at"] == changed["occurred_at"] == crm_events.utc(NOW)
    assert response.json()["handover"]["expires_at"] == changed["handover"]["expires_at"]
    assert changed["handover"]["active"] is True


def test_a_reply_while_already_taken_over_renews_it(redis, queue):
    # Near the real clock: patching `handover.time.time` moves `time.time` for
    # everyone, and a record saved a year ago has expired from the store.
    base = time.time()
    profile = user_store.get_or_create(PHONE)
    with patch("app.services.handover.time.time", return_value=base):
        handover.begin(profile)
    with patch("app.services.handover.time.time", return_value=base + 120):
        response = _sent()

    after = user_store.get(PHONE)
    assert after.handover_since == base, "a renewal is not a new takeover"
    assert after.handover_active_at == base + 120
    assert response.json()["handover"] == {
        "active": True, "expires_at": _expiry(base + 120), "occurred_at": crm_events.utc(base + 120),
    }


def test_a_reply_after_a_takeover_lapsed_starts_a_new_one(redis, queue):
    base = time.time() - settings.handover_idle_seconds - 60
    profile = user_store.get_or_create(PHONE)
    with patch("app.services.handover.time.time", return_value=base):
        handover.begin(profile)
    later = time.time()
    with patch("app.services.handover.time.time", return_value=later):
        _sent()
    after = user_store.get(PHONE)
    assert after.handover_since == later
    assert after.handover_active_at == later


def test_a_visitor_filed_under_their_bsuid_is_found_by_it(redis, queue):
    filed = user_store.get_or_create(BSUID)
    filed.username = "ada"
    user_store.save(filed)

    _sent(bsuid=BSUID)

    assert user_store.get(PHONE) is None, "no second record under the number"
    assert handover.active(user_store.get(BSUID))
    assert user_store.get(BSUID).history[-1].content == "Hello from the CRM"


def test_the_number_wins_over_the_bsuid(redis, queue):
    user_store.save(user_store.get_or_create(PHONE))
    user_store.save(user_store.get_or_create(BSUID))
    _sent(bsuid=BSUID)
    assert handover.active(user_store.get(PHONE))
    assert not handover.active(user_store.get(BSUID))


def test_after_a_send_the_key_then_agent_reply_then_the_takeover_in_that_order(redis, queue):
    response = _sent()

    order = [call[0] if call[0] != "set" else f"set {json.loads(call[2])}" for call in redis.calls]
    assert order == [
        "set {'state': 'sending'}",
        "set {'wa_message_id': 'wamid.SENT1'}",
        "rpush",
        "rpush",
    ]
    reply, changed = queue()
    assert reply["type"] == "agent_reply"
    assert reply["crm_message_id"] == REQUEST_ID
    assert reply["message"] == {"wa_message_id": "wamid.SENT1", "body": "Hello from the CRM"}
    assert reply["visitor"] == {"phone": PHONE, "bsuid": None, "profile_name": None}
    assert changed["type"] == "handover_changed"
    assert response.json()["handover"]["occurred_at"] == changed["occurred_at"]


def test_no_console_reply_and_no_ai_reply_for_a_crm_send(redis, queue):
    _sent()
    assert {event["type"] for event in queue()} == {"agent_reply", "handover_changed"}


def test_the_reply_is_in_the_history_and_the_audit_log_names_the_agent(redis, queue, audit_log):
    _sent()

    profile = user_store.get(PHONE)
    assert (profile.history[-1].role, profile.history[-1].content) == ("assistant", "Hello from the CRM")
    assert handover.active(profile), "the history write must not undo the takeover"

    message = audit_log.record_message.call_args.kwargs
    assert (message["role"], message["content"], message["source"]) == ("assistant", "Hello from the CRM", "crm_agent")
    assert message["turn"].key_id == PHONE
    assert message["turn"].conversation_id == profile.conversation_id, "a minted conversation id is saved"
    tool = audit_log.record_tool_call.call_args.kwargs
    assert tool["tool"] == "crm.reply"
    assert tool["input"] == {"agent_id": "user-7", "agent_name": "Mei", "request_id": REQUEST_ID}
    assert tool["output"] == "wamid.SENT1"
    assert audit.current() is None, "the turn is closed afterwards"


def test_the_console_shows_who_replied(redis, queue):
    from app.console import events

    events.clear()
    _sent()
    spans = [event for event in events.since(0) if event.tool == "crm.reply"]
    assert [event.type for event in spans] == [events.TOOL_START, events.TOOL_END]
    assert spans[0].input["agent"] == "Mei"
    assert spans[0].key_id == PHONE


def test_a_duplicate_queues_nothing_and_touches_nothing(redis, queue):
    _sent()
    before = user_store.get(PHONE)
    queued = len(queue())
    with patch("app.services.handover.time.time", return_value=before.handover_active_at + 60):
        _sent()
    after = user_store.get(PHONE)
    assert len(queue()) == queued
    assert after.handover_active_at == before.handover_active_at
    assert len(after.history) == len(before.history)


@pytest.mark.parametrize(
    "meta",
    [pytest.param(UNDELIVERABLE, id="refused"), pytest.param(_meta_answers(500), id="unknown")],
)
def test_a_send_that_did_not_go_through_queues_and_files_nothing(redis, queue, meta):
    with _meta(meta):
        _post()
    assert queue() == []
    assert user_store.get(PHONE) is None


def test_a_record_that_cannot_be_read_still_answers_sent(redis, queue, caplog):
    with patch.object(user_store, "get", side_effect=RuntimeError("store down")):
        response = _sent()
    assert response.status_code == 200
    assert response.json()["result"] == "sent"
    assert response.json()["handover"] is None
    assert [event["type"] for event in queue()] == ["agent_reply"]
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_a_takeover_that_fails_still_files_the_reply(redis, queue):
    with patch.object(handover, "hold", side_effect=RuntimeError("bug")):
        response = _sent()
    assert response.json()["result"] == "sent"
    assert response.json()["handover"] is None
    assert user_store.get(PHONE).history[-1].content == "Hello from the CRM"


def test_an_audit_log_that_fails_does_not_change_the_answer(redis, queue, audit_log):
    audit_log.record_message.side_effect = RuntimeError("mysql down")
    response = _sent()
    assert response.status_code == 200
    assert response.json()["handover"] is not None
    assert audit.current() is None


def test_with_the_events_switched_off_it_still_sends_and_takes_over(redis):
    """No `queue` fixture: CRM_EVENTS_ENABLED stays false."""
    response = _sent()
    assert response.json()["result"] == "sent"
    assert response.json()["handover"]["active"] is True
    assert handover.active(user_store.get(PHONE))


def test_the_console_sees_a_crm_takeover_and_can_answer_in_it(redis, queue):
    """One takeover for both (D8): what the CRM started, the console holds too."""
    _sent()
    headers = {"X-Console-Token": TOKEN}
    with patch("app.routers.console.settings.console_token", TOKEN), _meta(ACCEPTED):
        held = client.get("/console/handover", headers=headers).json()["customers"]
        reply = client.post("/console/reply", json={"key_id": PHONE, "text": "me too"}, headers=headers)
    assert [row["key_id"] for row in held] == [PHONE]
    assert reply.status_code == 200


# --- a takeover that reaches memory only (task 42.1, round 3 of its cold review) --


class _WriteFailingStore:
    """A Redis for `user_store` whose writes fail and whose reads work."""

    def __init__(self):
        self.data = {}
        self.fail_writes = False

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        if self.fail_writes:
            raise ConnectionError("redis is down")
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def store_redis():
    fake = _WriteFailingStore()
    user_store.reset()
    with patch.object(user_store, "_url", "redis://stand-in:6379/16"), \
            patch.object(user_store, "_client_factory", lambda url: fake):
        yield fake
    user_store.reset()


def test_a_takeover_that_reached_memory_only_is_not_reported_in_the_answer(redis, queue, store_redis):
    """Neither channel tells the CRM about it: no `handover_changed`, and no
    `handover` in the answer -- one value from both, or none (R3)."""
    store_redis.fail_writes = True

    response = _sent()

    assert response.json()["result"] == "sent"
    assert response.json()["handover"] is None
    assert [event["type"] for event in queue()] == ["agent_reply"]


def test_a_renewal_that_reached_memory_only_is_not_reported_in_the_answer(redis, queue, store_redis):
    user_store.save(user_store.get_or_create(PHONE))
    handover.begin(user_store.get(PHONE))
    store_redis.fail_writes = True
    queued = len(queue())

    response = _sent()

    assert response.json()["handover"] is None
    assert [event["type"] for event in queue()[queued:]] == ["agent_reply"]
