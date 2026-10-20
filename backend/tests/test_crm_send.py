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
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.services import crm_send
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


def _post(text: str = "Hello from the CRM", request_id: str = REQUEST_ID):
    body = json.dumps({
        "request_id": request_id,
        "visitor": {"phone": PHONE, "bsuid": None},
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
    assert response.json() == {"result": "sent", "wa_message_id": "wamid.SENT1", "handover": None}
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
