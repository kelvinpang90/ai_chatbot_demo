"""Every console event says which customer it belongs to (task 37.6a).

The console was one feed with everybody in it, and nothing on an event said
whose it was -- so a page that shows one customer's console (task 37.6b) had
nothing to filter on. Now each event carries the customer's `key_id`.

The hazard this suite exists for is quiet: an event that misses its customer
still shows up in the everybody feed, so nothing on screen looks wrong. It just
never appears when that customer is selected. So the guards below drive the
real entry points -- a voice note, a photo, a refused send, a web chat message,
a handover, a push -- and assert on every event each one produced, rather than
testing `emit` on its own and trusting the call sites.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.console import events
from app.main import app
from app.routers.whatsapp_webhook import _handle_incoming_message, dispatch_message
from app.services import handover, llm, notify, transcribe, whatsapp, whatsapp_media
from app.services.user_store import user_store

VOICE_MIME = "audio/ogg; codecs=opus"
PHOTO_MIME = "image/jpeg"


@pytest.fixture(autouse=True)
def clean_buffer():
    events.clear()
    yield
    events.clear()


def _in_conversation(phone: str) -> None:
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)


def _model_that_calls_a_tool(*_args, **_kwargs) -> str:
    """Stands in for llm.get_reply and emits what the real one emits.

    From inside the call, which is the point: the real tool runner emits its
    tool_start / tool_end / usage from this same stack, so whatever identity is
    in effect here is what those events get.
    """
    events.emit(type=events.TOOL_START, tool="erp_search_sku", tool_use_id="tu_1")
    events.emit(type=events.TOOL_END, tool="erp_search_sku", tool_use_id="tu_1", status="ok")
    events.emit(type=events.USAGE, model="claude-haiku-4-5", cost_myr=0.01)
    return "We have three."


def _all_belong_to(key_id: str) -> None:
    produced = events.since(0)
    assert produced, "nothing was emitted, so this proves nothing"
    strays = [(event.type, event.tool) for event in produced if event.key_id != key_id]
    assert not strays, f"events that would never show on {key_id}'s console: {strays}"


# --- the unit --------------------------------------------------------------------


def test_an_event_outside_any_customer_carries_no_customer():
    """The tools switch is for everybody at once. Blank is the honest value."""
    event = events.emit(type=events.TOOLS_SWITCHED, status="off")

    assert event.key_id == ""


def test_the_customer_being_served_is_stamped_on_what_is_emitted():
    events.set_customer("60129990001")

    assert events.emit(type=events.TOOL_START, tool="t").key_id == "60129990001"


def test_a_customer_named_at_the_call_wins_over_the_one_being_served():
    """A push or a handover names its customer outright, and must not be filed
    under whoever the thread happened to be serving."""
    events.set_customer("60129990001")

    event = events.emit(type=events.TOOL_START, tool="t", key_id="60129990002")

    assert event.key_id == "60129990002"


def test_the_customer_does_not_leak_into_the_next_test():
    """The same ContextVar hazard the outbox has; conftest clears it."""
    assert events.emit(type=events.TOOL_START, tool="t").key_id == ""


# --- WhatsApp, through the real entry point ---------------------------------------


def test_everything_a_voice_note_produces_belongs_to_the_sender():
    """The case the plan got wrong. The transcription span is emitted BEFORE the
    turn opens -- in dispatch_message, ahead of _handle_text_message -- so reading
    the customer off the audit turn would have left it blank."""
    phone = "60129996001"
    _in_conversation(phone)
    media = whatsapp_media.Media(content=b"OggS-pretend-opus", mime_type=VOICE_MIME)
    voice = {
        "id": f"wamid.{phone}.1",
        "from": phone,
        "type": "audio",
        "audio": {"id": "media-voice-1", "mime_type": VOICE_MIME, "voice": True},
    }

    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        with patch.object(transcribe, "transcribe", return_value="ada stock tak"):
            with patch.object(llm, "get_reply", side_effect=_model_that_calls_a_tool):
                dispatch_message(voice)

    assert {event.tool for event in events.since(0)} >= {"voice.transcribe", "erp_search_sku"}
    _all_belong_to(phone)


def test_everything_a_photo_produces_belongs_to_the_sender():
    phone = "60129996002"
    _in_conversation(phone)
    media = whatsapp_media.Media(content=b"\xff\xd8\xff\xe0-pretend-jpeg", mime_type=PHOTO_MIME)
    photo = {
        "id": f"wamid.{phone}.1",
        "from": phone,
        "type": "image",
        "image": {"id": "media-img-1", "mime_type": PHOTO_MIME, "sha256": "abc"},
    }

    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        with patch.object(llm, "get_reply", side_effect=_model_that_calls_a_tool):
            dispatch_message(photo)

    assert "image.download" in {event.tool for event in events.since(0)}
    _all_belong_to(phone)


def test_a_reply_meta_refused_is_filed_under_the_customer_it_was_for():
    """Emitted by the send loop, after dispatch_message has returned and the turn
    has closed -- so it depends on the customer staying set for the whole of the
    inbound message, not just the part that answers it."""
    phone = "60129996003"
    _in_conversation(phone)
    text = {"id": f"wamid.{phone}.1", "from": phone, "type": "text", "text": {"body": "hi"}}
    refused = whatsapp.WhatsAppSendError("WhatsApp refused a text message (HTTP 400): ...")

    with patch.object(llm, "get_reply", side_effect=_model_that_calls_a_tool):
        with patch.object(whatsapp, "send_raw", side_effect=refused):
            _handle_incoming_message(text)

    assert events.SEND_FAILED in {event.type for event in events.since(0)}
    _all_belong_to(phone)


def test_a_message_nobody_can_be_identified_from_is_filed_under_nobody():
    dispatch_message({"id": "wamid.anon", "type": "text", "text": {"body": "hi"}})

    failures = [event for event in events.since(0) if event.type == events.SEND_FAILED]
    assert failures and failures[0].key_id == ""


# --- the other ways in -----------------------------------------------------------


def test_everything_a_web_chat_message_produces_belongs_to_that_customer():
    """The same model, reached from the laptop instead of the phone."""
    phone = "60129996004"
    _in_conversation(phone)

    with patch.object(llm, "get_reply", side_effect=_model_that_calls_a_tool):
        response = TestClient(app).post(f"/api/chat/{phone}/message", json={"message": "hi"})

    assert response.status_code == 200
    _all_belong_to(phone)


def test_a_handover_is_filed_under_the_customer_taken_over():
    """Started from the console, where nobody is being served -- so the key has
    to come from the record, not from context."""
    phone = "60129996005"
    profile = user_store.get_or_create(phone)
    user_store.save(profile)

    handover.begin(profile, reason="wants a manager")
    handover.end(user_store.get(phone))

    _all_belong_to(phone)


def test_a_push_is_filed_under_the_customer_it_went_to():
    """Sent from a timer thread, which does not inherit anybody's context."""
    phone = "60129996006"
    _in_conversation(phone)

    with patch.object(whatsapp_media, "send_message"):
        notify.send_now(phone, "Your order is on its way.")

    _all_belong_to(phone)


def test_a_push_addressed_by_a_formatted_number_is_filed_under_the_filing_key():
    """The console's closing summary is sent to `profile.phone`, which is how the
    number was written down -- not necessarily how the record is filed. The
    console filters on the filing key, so that is what has to be on the event."""
    _in_conversation("60129996007")

    with patch.object(whatsapp_media, "send_message"):
        notify.send_now("+60 12-999 6007", "Thanks for coming.")

    _all_belong_to("60129996007")
