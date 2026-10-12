"""Where the CRM's events come from (task 40.2): every visitor message, every
reply that reached them, every takeover change, every delivery receipt.

The real paths throughout -- the signed webhook, `_handle_incoming_message`'s
send loop, the console endpoints, `handover` -- with Meta's send stubbed to
answer the way Meta does (a message id) and the queue's Redis replaced by a list
that is read back. Delivery itself is task 40.1's and `test_crm_events.py`'s.
"""
import hashlib
import hmac
import itertools
import json
import time
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers.whatsapp_webhook import _handle_incoming_message, dispatch_message
from app.services import crm_events, handover, llm, notify, transcribe, whatsapp, whatsapp_media
from app.services.user_store import user_store
from app.session_store import session_store
from app.tools import realestate

client = TestClient(app)

PHONE = "60123450001"
BSUID = "MY.4f9a2c7e"
TOKEN = "console-token-for-tests"
APP_SECRET = "not-a-real-app-secret"
HUMAN_PLEASE = "can I speak to a human please"


class FakeRedis:
    """Only what `enqueue` uses: append to a list."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])


@pytest.fixture
def queue(monkeypatch):
    """The CRM queue, switched on and read back as events."""
    fake = FakeRedis()
    crm_events.reset()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: fake)
    with patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "redis_url", "redis://stand-in:6379/16"), \
            patch.object(settings, "crm_events_secret", "test-secret"):
        yield lambda: [json.loads(raw) for raw in fake.lists.get(crm_events.QUEUE_KEY, [])]
    crm_events.reset()


@pytest.fixture
def console_token():
    with patch("app.routers.console.settings.console_token", TOKEN):
        yield


_sent_ids = itertools.count(1)


def _meta_accepts(payload: dict) -> httpx.Response:
    """What Meta answers a send with: the id it gave the message."""
    return httpx.Response(200, json={"messages": [{"id": f"wamid.out.{next(_sent_ids)}"}]})


@contextmanager
def _meta(**kwargs):
    with patch.object(whatsapp, "send_raw", side_effect=kwargs.get("side_effect", _meta_accepts)) as send:
        yield send


def _customer(key: str = PHONE, bot_id: str | None = "retail", **fields):
    profile = user_store.get_or_create(key)
    profile.bot_id = bot_id
    profile.username = fields.get("username")
    user_store.save(profile)
    return profile


def _message(kind: str, block: dict, seq: int = 1, sender: str = PHONE, **extra) -> dict:
    return {"id": f"wamid.in.{sender}.{seq}", "from": sender, "timestamp": "1760000000",
            "type": kind, kind: block, **extra}


def _text(text: str, seq: int = 1, sender: str = PHONE) -> dict:
    return _message("text", {"body": text}, seq, sender)


def _of(events, kind):
    return [event for event in events if event["type"] == kind]


def _post_webhook(value: dict) -> None:
    body = json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    with patch.object(settings, "whatsapp_app_secret", APP_SECRET):
        response = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"},
        )
    assert response.status_code == 200


# --- customer_message --------------------------------------------------------


@pytest.mark.parametrize(
    "message, body",
    [
        (_text("Ada stock earbuds?"), "Ada stock earbuds?"),
        (_message("image", {"id": "m1", "caption": "this one"}), "[image] this one"),
        (_message("image", {"id": "m1"}), "[image]"),
        (_message("document", {"id": "m1", "filename": "quote.pdf", "caption": "pls check"}),
         "[document] quote.pdf pls check"),
        (_message("interactive", {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}}),
         "Retail"),
        (_message("interactive", {"type": "button_reply", "button_reply": {"id": "qq:0", "title": "Do you deliver?"}}),
         "Do you deliver?"),
        (_message("interactive", {"type": "nfm_reply", "nfm_reply": {"response_json": "{}"}}), "[form]"),
        (_message("button", {"text": "Track my order", "payload": "track"}), "Track my order"),
        (_message("sticker", {"id": "m1"}), "[sticker]"),
    ],
    ids=["text", "image", "image-bare", "document", "list", "button", "form", "template-button", "sticker"],
)
def test_every_kind_of_message_reaches_the_crm_as_a_line_of_text(queue, message, body):
    _customer()
    with patch.object(llm, "get_reply", return_value="ok"), \
            patch.object(whatsapp_media, "fetch_media", side_effect=whatsapp_media.MediaError("no")):
        dispatch_message(message, {"wa_id": PHONE, "profile": {"name": "Aisha"}})

    (event,) = _of(queue(), "customer_message")
    assert event["message"] == {"wa_message_id": message["id"], "body": body}
    assert event["visitor"] == {"phone": PHONE, "bsuid": None, "profile_name": "Aisha"}
    assert event["occurred_at"] == "2025-10-09T08:53:20Z"  # Meta's timestamp, not ours


def test_a_visitor_who_hid_their_number_goes_by_their_bsuid(queue):
    message = {"id": "wamid.in.b.1", "from_user_id": BSUID, "type": "text", "text": {"body": "hi"}}
    with _meta():
        dispatch_message(message, {"user_id": BSUID, "profile": {"username": "aisha.k"}})

    (event,) = _of(queue(), "customer_message")
    assert event["visitor"] == {"phone": None, "bsuid": BSUID, "profile_name": "aisha.k"}


def test_a_message_with_no_timestamp_is_stamped_when_queued(queue, monkeypatch):
    monkeypatch.setattr(crm_events, "_now", lambda: 1_700_000_000.0)
    message = _text("hi")
    del message["timestamp"]
    dispatch_message(message, {})

    assert _of(queue(), "customer_message")[0]["occurred_at"] == "2023-11-14T22:13:20Z"


def _voice(seq: int = 1) -> dict:
    return _message("audio", {"id": f"voice-{seq}", "mime_type": "audio/ogg", "voice": True}, seq)


@contextmanager
def _hears(said=None, fails=False):
    media = whatsapp_media.Media(content=b"OggS", mime_type="audio/ogg")
    effect = transcribe.TranscriptionError("quota") if fails else None
    with patch.object(whatsapp_media, "fetch_media", return_value=media), \
            patch.object(transcribe, "transcribe", return_value=said, side_effect=effect) as heard, \
            patch.object(llm, "get_reply", return_value="ok"):
        yield heard


def test_a_voice_note_carries_what_was_said(queue):
    _customer()
    with _hears("nak tanya pasal earbuds"):
        dispatch_message(_voice(), {})

    assert _of(queue(), "customer_message")[0]["message"]["body"] == "[voice] nak tanya pasal earbuds"


def test_a_voice_note_that_would_not_transcribe_is_just_a_voice_note(queue):
    _customer()
    with _hears(fails=True):
        dispatch_message(_voice(), {})

    assert _of(queue(), "customer_message")[0]["message"]["body"] == "[voice]"


def test_a_visitor_over_the_cap_is_still_pushed_but_not_transcribed(queue):
    _customer()
    with _hears("anything") as heard, \
            patch.object(session_store, "check_and_increment_daily_count", return_value=False):
        dispatch_message(_voice(), {})

    heard.assert_not_called()
    assert _of(queue(), "customer_message")[0]["message"]["body"] == "[voice]"


def test_metas_retry_of_the_same_message_is_pushed_and_heard_once(queue):
    _customer()
    with _hears("hello") as heard:
        dispatch_message(_voice(seq=7), {})
        dispatch_message(_voice(seq=7), {})

    heard.assert_called_once()
    assert len(_of(queue(), "customer_message")) == 1


def test_a_message_from_nobody_we_can_name_is_not_pushed(queue):
    dispatch_message({"id": "wamid.x", "type": "text", "text": {"body": "hi"}}, {})
    assert queue() == []


# --- ai_reply ----------------------------------------------------------------


def test_a_bot_reply_is_pushed_with_metas_id_and_the_demo_it_came_from(queue):
    _customer(bot_id="retail")
    with _meta() as send, patch.object(llm, "get_reply", return_value="We have three."):
        _handle_incoming_message(_text("do you have earbuds"))

    (reply,) = _of(queue(), "ai_reply")
    sent = [call.args[0] for call in send.call_args_list if call.args[0].get("type") == "text"]
    assert reply["message"]["body"] == sent[-1]["text"]["body"]
    assert reply["message"]["wa_message_id"].startswith("wamid.out.")
    assert reply["bot_id"] == "retail"
    assert reply["visitor"]["phone"] == PHONE


def test_the_demo_menu_is_a_reply_from_no_demo_at_all(queue):
    with _meta():
        _handle_incoming_message(_text("hi", sender="60123450099"), {"wa_id": "60123450099"})

    (reply,) = _of(queue(), "ai_reply")
    assert reply["bot_id"] is None
    assert reply["message"]["body"].startswith("[list]")


def test_a_reply_meta_refused_is_not_pushed(queue):
    _customer()
    refused = whatsapp.WhatsAppSendError("HTTP 400")
    with _meta(side_effect=refused), patch.object(llm, "get_reply", return_value="We have three."):
        _handle_incoming_message(_text("do you have earbuds"))

    assert _of(queue(), "ai_reply") == []


def test_a_reply_meta_took_but_gave_no_id_for_is_not_pushed(queue, caplog):
    _customer()
    with _meta(side_effect=lambda payload: httpx.Response(200, json={})), \
            patch.object(llm, "get_reply", return_value="We have three."):
        with caplog.at_level("WARNING"):
            _handle_incoming_message(_text("do you have earbuds"))

    assert _of(queue(), "ai_reply") == []
    assert "no message id" in caplog.text


def test_the_chat_that_stands_in_for_a_refused_form_is_pushed(queue):
    _customer(bot_id="realestate")
    form = whatsapp.build_flow_message(PHONE, "Book a viewing", "flow-1", "tok", "Open form", realestate.SCREEN)

    def refuse_the_form(payload):
        if payload.get("type") == "interactive":
            raise whatsapp.WhatsAppSendError("#139000 Blocked by Integrity")
        return _meta_accepts(payload)

    with _meta(side_effect=refuse_the_form), \
            patch("app.routers.whatsapp_webhook.dispatch_message", return_value=[form]):
        _handle_incoming_message(_text("book a viewing"))

    (reply,) = _of(queue(), "ai_reply")
    assert reply["bot_id"] == "realestate"
    assert reply["message"]["body"] == realestate.undelivered_form_fallback(form).pick(None)


# --- console_reply and the closing summary -----------------------------------


def test_a_console_reply_is_the_consoles_and_carries_no_bot(queue, console_token):
    _customer()
    handover.begin(user_store.get(PHONE))
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts):
        response = client.post(
            "/console/reply", json={"key_id": PHONE, "text": "Boss, I'll check."},
            headers={"X-Console-Token": TOKEN},
        )
    assert response.status_code == 200

    (reply,) = _of(queue(), "console_reply")
    assert reply["message"]["body"] == "Boss, I'll check."
    assert reply["message"]["wa_message_id"].startswith("wamid.out.")
    assert "bot_id" not in reply
    assert _of(queue(), "ai_reply") == []


def test_the_closing_summary_is_the_bots_and_names_the_demo(queue):
    """What `/console/demo-summary` calls: `send_now` with the default source.
    The program wrote it, so it is an `ai_reply` (Kelvin, 2026-10-12)."""
    _customer(bot_id="food")
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts):
        notify.send_now(PHONE, "Thanks for trying the demo: 3 tool calls in 4 minutes.")

    (reply,) = _of(queue(), "ai_reply")
    assert reply["bot_id"] == "food"
    assert reply["message"]["body"] == "Thanks for trying the demo: 3 tool calls in 4 minutes."
    assert _of(queue(), "console_reply") == []


def test_a_reply_to_a_visitor_who_hid_their_number_names_their_bsuid(queue):
    """Meta addresses such a customer with `recipient`, not `to` (`whatsapp._recipient`)."""
    _customer(key=BSUID, bot_id="saas", username="aisha.k")
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts) as send:
        notify.send_now(BSUID, "Your ticket is open.")

    assert "to" not in send.call_args.args[0]
    (reply,) = _of(queue(), "ai_reply")
    assert reply["visitor"] == {"phone": None, "bsuid": BSUID, "profile_name": "aisha.k"}
    assert reply["bot_id"] == "saas"


def test_a_push_sent_as_a_template_is_filed_as_our_own_sentence(queue):
    _customer()
    push = notify.Push(0, "Your order is confirmed.", notify.Template(notify.ORDER_CONFIRMED, ("SO-1",)))
    window_long_closed = time.time() - notify.CUSTOMER_SERVICE_WINDOW_SECONDS - 60
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts) as send:
        notify._send(PHONE, push, window_long_closed)

    assert send.call_args.args[0]["type"] == "template"
    assert _of(queue(), "ai_reply")[0]["message"]["body"] == "Your order is confirmed."


# --- handover_changed --------------------------------------------------------


def _expiry_after(moment: float) -> str:
    return crm_events.utc(moment + settings.handover_idle_seconds)


def test_asking_for_a_person_starts_a_takeover_with_its_expiry(queue):
    _customer()
    with _meta(), patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
        _handle_incoming_message(_text(HUMAN_PLEASE))

    (changed,) = _of(queue(), "handover_changed")
    profile = user_store.get(PHONE)
    assert changed["handover"] == {"active": True, "expires_at": _expiry_after(profile.handover_active_at)}
    assert changed["visitor"]["phone"] == PHONE


def test_the_console_taking_over_renewing_and_giving_back(queue, console_token):
    _customer()
    headers = {"X-Console-Token": TOKEN}

    client.post("/console/handover", json={"key_id": PHONE, "active": True}, headers=headers)
    taken = user_store.get(PHONE).handover_active_at
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts), \
            patch("app.services.handover.time.time", return_value=taken + 120):
        client.post("/console/reply", json={"key_id": PHONE, "text": "hi"}, headers=headers)
    client.post("/console/handover", json={"key_id": PHONE, "active": False}, headers=headers)

    assert [event["handover"] for event in _of(queue(), "handover_changed")] == [
        {"active": True, "expires_at": _expiry_after(taken)},
        {"active": True, "expires_at": _expiry_after(taken + 120)},
        {"active": False, "expires_at": None},
    ]


def test_menu_ends_a_takeover(queue):
    _customer()
    handover.begin(user_store.get(PHONE))
    with _meta():
        _handle_incoming_message(_text("menu"))

    assert _of(queue(), "handover_changed")[-1]["handover"] == {"active": False, "expires_at": None}


def test_asking_twice_while_waiting_is_not_a_second_change(queue):
    _customer()
    handover.begin(user_store.get(PHONE))
    handover.begin(user_store.get(PHONE))

    assert len(_of(queue(), "handover_changed")) == 1


def test_giving_back_what_nobody_took_is_not_a_change(queue):
    _customer()
    handover.end(user_store.get(PHONE))

    assert _of(queue(), "handover_changed") == []


# --- delivery_status ---------------------------------------------------------


def _status(state: str, **extra) -> dict:
    return {"id": "wamid.out.77", "status": state, "timestamp": "1760000100", "recipient_id": PHONE, **extra}


def test_meta_receipts_are_passed_on(queue):
    failed = _status("failed", errors=[{"code": 131047, "title": "Re-engagement message"}])
    _post_webhook({"statuses": [_status("sent"), _status("delivered"), _status("read"), failed]})

    receipts = _of(queue(), "delivery_status")
    assert [r["status"]["status"] for r in receipts] == ["sent", "delivered", "read", "failed"]
    assert receipts[0]["status"] == {
        "wa_message_id": "wamid.out.77", "status": "sent", "error_code": None, "error_title": None,
    }
    assert receipts[3]["status"]["error_code"] == 131047
    assert receipts[3]["status"]["error_title"] == "Re-engagement message"
    assert receipts[0]["visitor"] == {"phone": PHONE, "bsuid": None, "profile_name": None}
    assert receipts[0]["occurred_at"] == "2025-10-09T08:55:00Z"


def test_a_receipt_meta_invents_later_is_skipped(queue):
    _post_webhook({"statuses": [_status("deleted"), _status("warning")]})
    assert queue() == []


def test_a_receipt_for_a_visitor_who_hid_their_number_names_their_bsuid(queue):
    _post_webhook({"statuses": [_status("read", recipient_id=BSUID)]})
    assert _of(queue(), "delivery_status")[0]["visitor"]["bsuid"] == BSUID
    assert _of(queue(), "delivery_status")[0]["visitor"]["phone"] is None


def test_a_webhook_with_both_messages_and_receipts_pushes_both(queue):
    _customer()
    with _meta(), patch.object(llm, "get_reply", return_value="ok"):
        _post_webhook({"messages": [_text("hello")], "statuses": [_status("read")]})

    kinds = [event["type"] for event in queue()]
    assert "customer_message" in kinds and "delivery_status" in kinds


# --- order -------------------------------------------------------------------


def test_asking_for_a_person_is_message_then_takeover_then_the_handover_line(queue):
    _customer()
    with _meta(), patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
        _handle_incoming_message(_text(HUMAN_PLEASE))

    assert [event["type"] for event in queue()] == ["customer_message", "handover_changed", "ai_reply"]
    assert queue()[1]["handover"]["active"] is True


def test_a_console_reply_is_the_reply_then_the_renewal(queue, console_token):
    _customer()
    handover.begin(user_store.get(PHONE))
    with patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts):
        client.post("/console/reply", json={"key_id": PHONE, "text": "hi"}, headers={"X-Console-Token": TOKEN})

    assert [event["type"] for event in queue()] == ["handover_changed", "console_reply", "handover_changed"]


# --- switched off ------------------------------------------------------------


def test_switched_off_a_whole_conversation_queues_nothing(console_token, monkeypatch):
    touched = []
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: touched.append(url))
    crm_events.reset()
    _customer()
    headers = {"X-Console-Token": TOKEN}

    with _meta() as send, patch.object(llm, "get_reply", return_value="We have three."), \
            patch.object(whatsapp_media, "send_message", side_effect=_meta_accepts) as console_send:
        _post_webhook({"messages": [_text("do you have earbuds", seq=1)]})
        _post_webhook({"messages": [_text(HUMAN_PLEASE, seq=2)]})
        client.post("/console/reply", json={"key_id": PHONE, "text": "hi"}, headers=headers)
        client.post("/console/handover", json={"key_id": PHONE, "active": False}, headers=headers)
        _post_webhook({"statuses": [_status("read")]})

    # The conversation really happened: the bot answered and the console's line went out.
    assert any(call.args[0].get("type") == "text" for call in send.call_args_list)
    console_send.assert_called_once()
    assert touched == []
