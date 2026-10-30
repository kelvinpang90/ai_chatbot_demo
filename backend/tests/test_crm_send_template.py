"""`POST /internal/crm/send-template` (task 46.2): a whitelisted template, sent
through the same key, classification, takeover and history as a text reply.

The contract is `docs/chatbot-phase3.md` sections 5.3, 6 (item 2) and 7 in
acuven_crm_demo. Meta is stubbed at `httpx.post` and the key's Redis is
`test_crm_send`'s fake, so this file proves the template path walks the same
steps -- `test_crm_send.py` is where each step is tested in depth.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import httpx
import pytest

from app.config import CrmTemplate, settings
from app.services import crm_events, handover
from app.services.user_store import user_store
# The key's fake Redis, the event queue and the audit store, shared on purpose:
# one key space for both routes is the point. `configured` is autouse there and
# has to be named here to stay so.
from tests.test_crm_send import (  # noqa: F401
    ACCEPTED,
    KEY,
    NOW,
    PHONE,
    REQUEST_ID,
    SECRET,
    UNDELIVERABLE,
    _meta,
    _meta_answers,
    _post as _post_text,
    _stored,
    audit_log,
    client,
    configured,
    queue,
    redis,
)

URL = "/internal/crm/send-template"

FOLLOWUP = {
    "name": "crm_followup",
    "language": "en",
    "category": "UTILITY",
    "params": [{"label": "Visitor name", "max_len": 20}],
    "body": "Hi {{1}}, this is Acuven Technology following up on your recent enquiry.",
}
FOLLOWUP_CN = {
    "name": "crm_followup",
    "language": "zh_CN",
    "category": "UTILITY",
    "params": [{"label": "访客称呼", "max_len": 20}],
    "body": "您好 {{1}}，这里是 Acuven Technology。",
}
RENDERED = "Hi Mei, this is Acuven Technology following up on your recent enquiry."


@pytest.fixture(autouse=True)
def whitelist():
    templates = [CrmTemplate.model_validate(entry) for entry in (FOLLOWUP, FOLLOWUP_CN)]
    with patch.object(settings, "crm_templates", templates):
        yield


def _request(**template) -> dict:
    return {
        "request_id": REQUEST_ID,
        "visitor": {"phone": PHONE, "bsuid": None},
        "template": {"name": "crm_followup", "language": "en", "params": ["  Mei "], **template},
        "agent": {"id": "user-7", "name": "Mei Lin"},
    }


def _post(request: dict | None = None, *, secret: str = SECRET):
    body = json.dumps(_request() if request is None else request, ensure_ascii=False).encode()
    signature = "sha256=" + hmac.new(secret.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(URL, content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def _sent(request: dict | None = None):
    with _meta(ACCEPTED):
        return _post(request)


def _expiry(moment: float) -> str:
    return crm_events.utc(moment + settings.handover_idle_seconds)


# --- the door and the whitelist -------------------------------------------------


def test_without_a_secret_it_is_503(redis):
    with patch.object(settings, "crm_send_secret", ""), _meta(ACCEPTED) as meta:
        assert _post().status_code == 503
    meta.assert_not_called()


def test_a_bad_signature_is_401_even_for_a_template_off_the_whitelist(redis):
    with _meta(ACCEPTED) as meta:
        assert _post(_request(name="not_listed"), secret="wrong").status_code == 401
    meta.assert_not_called()


@pytest.mark.parametrize(
    "request_",
    [
        {**_request(), "request_id": "not-a-uuid"},
        {**_request(), "visitor": {"phone": "+60123456789", "bsuid": None}},
        {**_request(), "agent": {"id": "user-7"}},
        {**_request(), "template": {"name": "crm_followup", "language": "en"}},
        _request(name="  "),
        _request(params="Mei"),
        _request(params=[1]),
    ],
    ids=["request-id", "phone", "agent", "no-params", "blank-name", "params-not-a-list", "param-not-a-string"],
)
def test_a_malformed_request_is_422(redis, request_):
    with _meta(ACCEPTED) as meta:
        assert _post(request_).status_code == 422
    meta.assert_not_called()


@pytest.mark.parametrize(
    "template",
    [
        {"name": "order_confirmed"},
        {"language": "zh_cn"},
        {"language": "ms"},
        {"params": []},
        {"params": ["Mei", "Acuven"]},
        {"params": ["x" * 21]},
        {"params": ["   "]},
        {"params": ["Mei\nLin"]},
        {"params": ["Mei\tLin"]},
        {"params": ["Mei    Lin"]},
    ],
    ids=["not-listed", "language-case", "language-not-listed", "too-few", "too-many", "too-long", "blank",
         "newline", "tab", "four-spaces"],
)
def test_what_the_whitelist_refuses_is_422_and_neither_takes_the_key_nor_calls_meta(redis, queue, template):
    with _meta(ACCEPTED) as meta:
        response = _post(_request(**template))
    assert response.status_code == 422
    meta.assert_not_called()
    assert redis.calls == [], "the key is not touched"
    assert queue() == []


def test_an_empty_whitelist_refuses_everything(redis):
    with patch.object(settings, "crm_templates", []), _meta(ACCEPTED) as meta:
        assert _post().status_code == 422
    meta.assert_not_called()


def test_a_refusal_does_not_echo_the_value(redis):
    with _meta(ACCEPTED):
        response = _post(_request(params=["Secret\nName"]))
    assert "Secret" not in response.text


# --- sent -----------------------------------------------------------------------


def test_a_template_goes_to_meta_with_the_trimmed_values(redis, queue):
    with _meta(ACCEPTED) as meta:
        response = _post()

    assert response.status_code == 200
    sent = meta.call_args.kwargs["json"]
    assert sent["to"] == PHONE
    assert sent["type"] == "template"
    assert sent["template"] == {
        "name": "crm_followup",
        "language": {"code": "en"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "Mei"}]}],
    }


def test_the_answer_is_sends_with_the_rendered_body(redis, queue):
    response = _sent()

    taken = user_store.get(PHONE).handover_active_at
    assert response.json() == {
        "result": "sent",
        "wa_message_id": "wamid.SENT1",
        "handover": {"active": True, "expires_at": _expiry(taken), "occurred_at": crm_events.utc(taken)},
        "body": RENDERED,
    }
    assert json.loads(redis.values[KEY]) == {"wa_message_id": "wamid.SENT1"}
    assert redis.ttls[KEY] == 48 * 60 * 60


def test_the_chinese_template_is_found_by_its_language(redis, queue):
    with _meta(ACCEPTED) as meta:
        response = _post(_request(language="zh_CN", params=["李先生"]))
    assert meta.call_args.kwargs["json"]["template"]["language"] == {"code": "zh_CN"}
    assert response.json()["body"] == "您好 李先生，这里是 Acuven Technology。"


# --- the key, shared with `send` --------------------------------------------------


def test_the_same_request_twice_reaches_the_visitor_once(redis, queue):
    _sent()
    with _meta(ACCEPTED) as meta:
        again = _post()
    meta.assert_not_called()
    assert again.status_code == 200
    # No `body` on a duplicate: the key holds Meta's id alone.
    assert again.json() == {"result": "duplicate", "wa_message_id": "wamid.SENT1", "handover": None}


def test_a_request_id_a_text_send_used_is_a_duplicate_here(redis, queue):
    with _meta(ACCEPTED):
        _post_text()
    with _meta(ACCEPTED) as meta:
        response = _post()
    meta.assert_not_called()
    assert response.json()["result"] == "duplicate"


def test_a_request_id_a_template_used_is_a_duplicate_for_a_text_send(redis, queue):
    _sent()
    with _meta(ACCEPTED) as meta:
        response = _post_text()
    meta.assert_not_called()
    assert response.json()["result"] == "duplicate"


def test_while_a_text_send_holds_the_key_a_template_is_409(redis):
    redis.values[KEY] = json.dumps({"state": "sending"})
    with _meta(ACCEPTED) as meta:
        response = _post()
    meta.assert_not_called()
    assert (response.status_code, response.json()) == (409, {"result": "in_progress"})


def test_the_key_is_taken_with_nx_and_a_120_second_expiry_before_meta_is_called(redis):
    seen = []

    def answer(url, **kwargs):
        seen.append((dict(redis.values), dict(redis.ttls)))
        return ACCEPTED(url, **kwargs)

    with _meta(answer):
        _post()
    values, ttls = seen[0]
    assert json.loads(values[KEY]) == {"state": "sending"}
    assert ttls[KEY] == 120


# --- what Meta said -------------------------------------------------------------


def test_a_refusal_is_502_and_frees_the_key_so_a_retry_sends(redis, queue):
    with _meta(UNDELIVERABLE):
        response = _post()
    assert response.status_code == 502
    assert response.json() == {"result": "rejected", "error_code": 131026, "error_title": "(#131026) Message undeliverable"}
    assert KEY not in redis.values
    assert queue() == []
    assert user_store.get(PHONE) is None, "nothing filed for a template that did not go out"

    with _meta(ACCEPTED) as meta:
        assert _post().json()["result"] == "sent"
    meta.assert_called_once()


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(_meta_answers(500), id="5xx"),
        pytest.param(httpx.ReadTimeout("timed out"), id="timeout"),
        pytest.param(httpx.ConnectError("refused"), id="connect"),
        pytest.param(_meta_answers(200, {"messages": []}), id="no-id"),
    ],
)
def test_when_it_is_not_known_whether_meta_took_it_the_answer_is_504_and_the_key_stays(redis, queue, outcome):
    with _meta(outcome):
        response = _post()
    assert (response.status_code, response.json()) == (504, {"result": "unknown"})
    assert _stored(redis) == {"state": "sending"}
    assert queue() == []

    with _meta(ACCEPTED) as meta:
        assert _post().status_code == 409
    meta.assert_not_called()


def test_without_redis_nothing_is_sent_and_the_answer_is_503(redis):
    redis.broken.add("set")
    with _meta(ACCEPTED) as meta:
        response = _post()
    assert (response.status_code, response.json()) == (503, {"result": "unavailable"})
    meta.assert_not_called()


# --- after the send ---------------------------------------------------------------


def test_agent_reply_says_it_was_a_template_and_carries_the_rendered_body(redis, queue):
    _sent()
    reply, changed = queue()
    assert reply["type"] == "agent_reply"
    assert reply["crm_message_id"] == REQUEST_ID
    assert reply["message"] == {
        "wa_message_id": "wamid.SENT1",
        "body": RENDERED,
        "kind": "template",
        "template_name": "crm_followup",
    }
    assert changed["type"] == "handover_changed"


def test_a_template_starts_a_takeover(redis, queue):
    response = _sent()
    profile = user_store.get(PHONE)
    assert handover.active(profile)
    (changed,) = [event for event in queue() if event["type"] == "handover_changed"]
    assert response.json()["handover"]["occurred_at"] == changed["occurred_at"]


def test_a_template_while_taken_over_renews_it(redis, queue):
    base = time.time()
    profile = user_store.get_or_create(PHONE)
    with patch("app.services.handover.time.time", return_value=base):
        handover.begin(profile)
    with patch("app.services.handover.time.time", return_value=base + 120):
        response = _sent()

    after = user_store.get(PHONE)
    assert after.handover_since == base, "a renewal is not a new takeover"
    assert after.handover_active_at == base + 120
    assert response.json()["handover"]["expires_at"] == _expiry(base + 120)


def test_the_history_gets_the_rendered_body_and_the_audit_log_names_the_agent_and_template(redis, queue, audit_log):
    _sent()

    profile = user_store.get(PHONE)
    assert (profile.history[-1].role, profile.history[-1].content) == ("assistant", RENDERED)
    message = audit_log.record_message.call_args.kwargs
    assert (message["role"], message["content"], message["source"]) == ("assistant", RENDERED, "crm_agent")
    tool = audit_log.record_tool_call.call_args.kwargs
    # Still `crm.reply`: the console labels a CRM agent's line by this row (task 44).
    assert tool["tool"] == "crm.reply"
    assert tool["input"] == {
        "agent_id": "user-7", "agent_name": "Mei Lin", "request_id": REQUEST_ID,
        "template": "crm_followup", "language": "en",
    }
    assert tool["output"] == "wamid.SENT1"


def test_the_console_shows_who_sent_which_template(redis, queue):
    from app.console import events

    events.clear()
    _sent()
    start = next(event for event in events.since(0) if event.tool == "crm.reply" and event.type == events.TOOL_START)
    assert start.input == {"to": PHONE, "agent": "Mei Lin", "template": "crm_followup", "language": "en"}
    taken = next(event for event in events.since(0) if event.tool == "handover" and event.type == events.TOOL_START)
    assert taken.input["reason"] == "sent a template from the CRM by Mei Lin"
