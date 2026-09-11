import itertools
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.console import events
from app.main import app
from app.routers.whatsapp_webhook import (
    IMAGE_UNREADABLE_MESSAGE,
    UNSUPPORTED_TYPE_MESSAGE,
    VOICE_UNREADABLE_MESSAGE,
    Sender,
    _extract_messages,
    _handle_incoming_message,
    _identify,
    _remember_identity,
    _resolve_product_choice,
    _resolve_quick_question,
    dispatch_message,
)
from app.services import llm, outbox, transcribe, whatsapp, whatsapp_media
from app.services.user_store import user_store

client = TestClient(app)


# Row and button lengths used to be cut here, by a local `_truncate`. They are
# cut in `whatsapp.list_row` and `build_quick_reply_buttons` now, where the rest
# of Meta's limits already live -- see test_whatsapp.py.


def test_extract_messages_reads_nested_meta_payload():
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wamid.1"}, {"id": "wamid.2"}]}}]}]
    }
    pairs = _extract_messages(payload)
    assert [message["id"] for message, _contact in pairs] == ["wamid.1", "wamid.2"]


def test_extract_messages_handles_missing_messages_key():
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "s1"}]}}]}]}
    assert _extract_messages(payload) == []


def test_resolve_quick_question_returns_text_for_valid_index():
    assert _resolve_quick_question("retail", "qq:0") is not None


def test_resolve_quick_question_returns_none_for_bad_id():
    assert _resolve_quick_question("retail", "not-a-qq-id") is None
    assert _resolve_quick_question("retail", "qq:999") is None
    assert _resolve_quick_question("does-not-exist", "qq:0") is None


def test_a_tapped_product_carries_both_the_id_and_the_name():
    """The id is what makes it that product and not the one below it; the name
    is what makes the sentence read like something a person said."""
    said = _resolve_product_choice("sku:12", "TWS Earbuds Pro")

    assert "12" in said and "TWS Earbuds Pro" in said


def test_a_tapped_product_survives_a_row_meta_echoes_back_without_its_title():
    assert "12" in _resolve_product_choice("sku:12", "")


def test_a_row_that_is_not_a_product_is_left_to_whoever_owns_it():
    assert _resolve_product_choice("retail", "Retail") is None
    assert _resolve_product_choice("qq:0", "Do you deliver?") is None


def test_verify_webhook_get_returns_challenge_when_token_matches():
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "abc123",
        },
    )
    assert response.status_code == 200
    assert response.text == "abc123"


def test_verify_webhook_get_rejects_wrong_token():
    response = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "definitely-wrong", "hub.challenge": "abc123"},
    )
    assert response.status_code == 403


# -- files a tool produced travelling with the reply --------------------------
#
# The seam between `app.services.outbox` and this router: a tool cannot send a
# WhatsApp message itself, so it leaves the file here and `dispatch_message` is
# supposed to pick it up. Both halves look correct in isolation whether or not
# they are connected, which is what these two are for.


def _text_message(phone: str, body: str) -> dict:
    return {"id": f"wamid.{phone}.1", "from": phone, "type": "text", "text": {"body": body}}


def _in_conversation(phone: str) -> None:
    """Skip the demo menu; it has its own tests."""
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)


def test_a_file_a_tool_produced_is_sent_after_the_words_explaining_it():
    phone = "60129990001"
    _in_conversation(phone)

    def reply_and_attach(*_args, **_kwargs) -> str:
        outbox.add(outbox.Attachment("media-1", "INV-2026-0007.pdf", "your e-Invoice"))
        return "Here is your invoice."

    with patch.object(llm, "get_reply", side_effect=reply_and_attach):
        sent = dispatch_message(_text_message(phone, "send me the invoice"))

    words, document = sent
    assert words["type"] == "text"
    assert document["type"] == "document"
    assert document["to"] == phone
    assert document["document"]["filename"] == "INV-2026-0007.pdf"


def test_a_file_does_not_leak_from_one_conversation_into_the_next():
    """The outbox is opened per inbound message. Left over, an invoice would be
    sent a second time -- to whoever wrote next."""
    first, second = "60129990002", "60129990003"
    _in_conversation(first)
    _in_conversation(second)

    def attach_once(*_args, **_kwargs) -> str:
        outbox.add(outbox.Attachment("media-2", "INV-2026-0008.pdf", ""))
        return "Sent."

    with patch.object(llm, "get_reply", side_effect=attach_once):
        dispatch_message(_text_message(first, "invoice please"))
    with patch.object(llm, "get_reply", return_value="Anything else?"):
        sent = dispatch_message(_text_message(second, "hello"))

    assert [message["type"] for message in sent] == ["text"]


# -- the number they write from is who they are (task 32) ---------------------
#
# There used to be a second menu between the demo list and the assistant, on
# which the visitor picked a made-up customer to pretend to be. It is gone: the
# record now hangs off the number WhatsApp already told us, so the same person
# writing again next week is the same person.


def _list_reply(phone: str, option_id: str, seq: int = 9, title: str = "") -> dict:
    reply = {"id": option_id, **({"title": title} if title else {})}
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": reply},
    }


def test_tapping_a_product_reaches_the_model_as_the_order_it_is():
    """The acceptance criterion for the list: a tap has to start the ordering
    conversation, not sit there as an interactive message nobody handles."""
    phone = "60129991010"
    _in_conversation(phone)
    seen = {}

    def capture(bot, customer, history, image=None):
        seen["said"] = history[-1].content
        return "How many would you like?"

    with patch.object(llm, "get_reply", side_effect=capture):
        sent = dispatch_message(_list_reply(phone, "sku:12", title="TWS Earbuds Pro"))

    assert "12" in seen["said"] and "TWS Earbuds Pro" in seen["said"]
    assert [message["type"] for message in sent] == ["text"]
    # And it is in the record, so the next message is answered in its light.
    assert [m.role for m in user_store.get(phone).history] == ["user", "assistant"]


def test_choosing_a_demo_goes_straight_to_the_greeting():
    """No "who would you like to be" in between, and no identity list to answer."""
    phone = "60129991001"

    sent = dispatch_message(_list_reply(phone, "retail"))

    assert [message["type"] for message in sent] == ["text", "interactive"]
    assert "Who would you like to be" not in json.dumps(sent)
    assert user_store.get(phone).bot_id == "retail"


def test_the_model_is_handed_the_number_that_actually_wrote_in():
    """The whole point of the swap. Handed a real number the assistant can look
    them up; handed a fixture's it would look up a stranger."""
    phone = "60129991002"
    _in_conversation(phone)
    seen = {}

    def capture(bot, customer, history, image=None):
        seen["customer"] = customer
        return "Sure."

    with patch.object(llm, "get_reply", side_effect=capture):
        dispatch_message(_text_message(phone, "do you have earbuds"))

    assert seen["customer"].phone == phone


def test_the_conversation_is_on_file_after_the_reply():
    """Nothing is remembered across days unless it is written down at the time."""
    phone = "60129991003"
    _in_conversation(phone)

    with patch.object(llm, "get_reply", return_value="We have three."):
        dispatch_message(_text_message(phone, "do you have earbuds"))

    stored = user_store.get(phone)
    assert [(m.role, m.content) for m in stored.history] == [
        ("user", "do you have earbuds"),
        ("assistant", "We have three."),
    ]


def test_writing_in_again_continues_where_they_left_off():
    """The acceptance criterion, minus the phone: a second conversation must
    reach the model with the first one already in front of it, and must not send
    them back to the demo menu."""
    phone = "60129991004"
    dispatch_message(_list_reply(phone, "retail"))
    with patch.object(llm, "get_reply", return_value="We have three."):
        dispatch_message(_text_message(phone, "do you have earbuds"))

    seen = {}

    def capture(bot, customer, history, image=None):
        seen["bot"] = bot.id
        seen["history"] = [m.content for m in history]
        return "Ten in KL."

    with patch.object(llm, "get_reply", side_effect=capture):
        sent = dispatch_message({**_text_message(phone, "how many left?"), "id": "wamid.later"})

    assert seen["bot"] == "retail"  # not shown the menu again
    assert seen["history"] == ["do you have earbuds", "We have three.", "how many left?"]
    assert [message["type"] for message in sent] == ["text"]


def test_menu_starts_the_conversation_over_without_forgetting_the_person():
    phone = "60129991005"
    _in_conversation(phone)
    profile = user_store.get(phone)
    profile.display_name = "Lee Kok Hao"
    user_store.save(profile)
    with patch.object(llm, "get_reply", return_value="We have three."):
        dispatch_message(_text_message(phone, "do you have earbuds"))

    sent = dispatch_message({**_text_message(phone, "menu"), "id": "wamid.menu"})

    assert [message["type"] for message in sent] == ["interactive"]
    reopened = user_store.get(phone)
    assert reopened.bot_id is None and reopened.history == []
    assert reopened.display_name == "Lee Kok Hao"  # still the same customer


def test_a_number_that_only_ever_saw_the_menu_leaves_no_record():
    """A wrong number says one word and goes. Filing it would put a customer on
    the books who never asked for anything -- and, from task 34, into the CRM."""
    stranger, browser = "60129991006", "60129991007"

    dispatch_message(_text_message(stranger, "hi"))
    dispatch_message(_text_message(browser, "menu"))

    assert user_store.get(stranger) is None
    assert user_store.get(browser) is None


def test_however_the_number_is_written_it_is_the_same_customer():
    """Task 33 leans on this: a number typed on a laptop has to find the history
    from a phone. WhatsApp sends bare digits, people type spaces and dashes."""
    _in_conversation("60129991008")

    assert user_store.get("+60 12-999 1008").bot_id == "retail"


# -- a failed reply must be loud, and must not poison the record ---------------


def test_a_reply_that_cannot_be_sent_does_not_enter_the_history():
    """One bad turn used to be written to Redis and shown to the model on every
    later message, so the number stayed broken until someone deleted the key."""
    phone = "60129992001"
    _in_conversation(phone)
    with patch.object(llm, "get_reply", return_value="We have three."):
        dispatch_message(_text_message(phone, "do you have earbuds"))

    # A reply no builder will accept: get_reply is contracted not to do this, so
    # reaching here at all means a bug, and the turn must be dropped whole.
    with patch.object(llm, "get_reply", return_value=""):
        with pytest.raises(whatsapp.UnsendableMessage):
            dispatch_message({**_text_message(phone, "and how many left?"), "id": "wamid.bad"})

    stored = user_store.get(phone)
    assert [m.content for m in stored.history] == ["do you have earbuds", "We have three."]


def test_a_rejected_send_reaches_the_console_rather_than_only_the_log():
    """On the director's screen a silent failure is indistinguishable from the
    model thinking. It should not be."""
    phone = "60129992002"
    _in_conversation(phone)
    events.clear()

    refused = whatsapp.WhatsAppSendError("WhatsApp refused a text message (HTTP 400): ...")
    with patch.object(llm, "get_reply", return_value="We have three."):
        with patch.object(whatsapp, "send_raw", side_effect=refused):
            _handle_incoming_message(_text_message(phone, "do you have earbuds"))

    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1
    assert failures[0].status == "error"
    assert "HTTP 400" in failures[0].output
    events.clear()


def test_a_message_that_blows_up_is_never_answered_with_silence_in_the_log():
    """`_handle_incoming_message` is the last catcher. Whatever it swallows has
    to leave both a traceback and a console event behind."""
    phone = "60129992003"
    _in_conversation(phone)
    events.clear()

    with patch.object(llm, "get_reply", side_effect=RuntimeError("tool blew up")):
        _handle_incoming_message(_text_message(phone, "do you have earbuds"))

    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1
    assert "tool blew up" in failures[0].output
    events.clear()


def test_the_customer_sees_typing_before_the_slow_work_rather_than_after_it():
    """Sent afterwards it would be decoration. The whole point is that it covers
    the seconds the real tool calls take, so the order is the feature."""
    phone = "60129992004"
    _in_conversation(phone)
    order = []

    def note_reply(*_args, **_kwargs) -> str:
        order.append("llm")
        return "We have three."

    def note_send(payload: dict) -> None:
        order.append("typing" if "typing_indicator" in payload else payload.get("type"))

    with patch.object(llm, "get_reply", side_effect=note_reply):
        with patch.object(whatsapp, "send_raw", side_effect=note_send):
            _handle_incoming_message(_text_message(phone, "do you have earbuds"))

    assert order == ["typing", "llm", "text"]


def test_a_refused_typing_indicator_still_leaves_the_customer_with_an_answer():
    """The failure is contained in `send_typing_indicator`, not caught by the
    blanket handler around the whole turn -- which would have dropped the reply."""
    phone = "60129992005"
    _in_conversation(phone)
    events.clear()
    sent = []

    def refuse_only_the_indicator(payload: dict) -> None:
        if "typing_indicator" in payload:
            raise whatsapp.WhatsAppSendError("WhatsApp refused a ? message (HTTP 400): ...")
        sent.append(payload)

    with patch.object(llm, "get_reply", return_value="We have three."):
        with patch.object(whatsapp, "send_raw", side_effect=refuse_only_the_indicator):
            _handle_incoming_message(_text_message(phone, "do you have earbuds"))

    assert [p["type"] for p in sent] == ["text"]
    # Nothing the customer or the room needs to know about: they got the answer.
    assert [e for e in events.since(0) if e.type == events.SEND_FAILED] == []
    events.clear()


# -- a customer who has hidden their phone number (Meta, 2026) -----------------
#
# Meta now lets a WhatsApp user keep their number to themselves and be reached by
# a username instead. `from` and `wa_id` simply stop appearing. What always
# appears is the business-scoped user id -- on the message as `from_user_id`, on
# the contact as `user_id` -- and the username, which lives only in the contact
# block this router used to throw away.

BSUID = "MY.13491208655302741918"

# Message ids are deduplicated process-wide and for good reason, so every payload
# a test builds needs its own.
_hidden_ids = itertools.count(1)


def _hidden_number_payload(text: str, username: str = "kelvin.p") -> dict:
    """One inbound message from someone with no phone number, in Meta's shape."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {
                                    "profile": {"name": "Kelvin", "username": username},
                                    "user_id": BSUID,
                                }
                            ],
                            "messages": [
                                {
                                    "id": f"wamid.hidden.{next(_hidden_ids)}",
                                    "from_user_id": BSUID,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _one(payload: dict) -> tuple[dict, dict]:
    (pair,) = _extract_messages(payload)
    return pair


def test_the_contact_block_is_no_longer_thrown_away():
    """`username` appears nowhere else in the payload, so dropping the contact
    left nothing to call a customer with no phone number by."""
    message, contact = _one(_hidden_number_payload("hi"))

    assert contact["profile"]["username"] == "kelvin.p"
    assert message["from_user_id"] == BSUID


def test_a_message_with_no_phone_number_is_answered_rather_than_dropped():
    message, contact = _one(_hidden_number_payload("hi"))

    sent = dispatch_message(message, contact)

    assert [m["type"] for m in sent] == ["interactive"]  # the demo menu


def test_such_a_customer_is_filed_under_their_user_id_and_called_by_their_handle():
    message, contact = _one(_hidden_number_payload("hi"))
    dispatch_message(message, contact)

    picked = {
        **message,
        "id": "wamid.hidden.pick",
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": {"id": "retail"}},
    }
    dispatch_message(picked, contact)

    stored = user_store.get(BSUID)
    assert stored is not None
    assert stored.key_id == BSUID
    assert stored.user_id == BSUID
    assert stored.username == "kelvin.p"
    # What this was for: with no number to go on, the handle is what we call them.
    assert stored.display_name == "kelvin.p"
    assert stored.phone is None


def test_the_reply_is_addressed_by_user_id_not_by_a_to_field():
    """A BSUID in `to` would be another 400. Meta addresses these with
    `recipient` -- see the warning on whatsapp._recipient: not yet proved live."""
    message, contact = _one(_hidden_number_payload("hi"))

    (menu,) = dispatch_message(message, contact)

    assert menu["recipient"] == BSUID
    assert "to" not in menu


def test_a_phone_number_is_still_addressed_the_way_it_always_was():
    """The ordinary case must not have moved underneath the change."""
    payload = whatsapp.build_text_message("60123456789", "hello")

    assert payload["to"] == "60123456789"
    assert "recipient" not in payload


def test_a_sender_we_cannot_identify_is_loud_rather_than_dropped():
    """This used to be a bare `return []` -- the last inbound failure that said
    nothing at all, which is how the empty-reply outage stayed hidden for a
    whole conversation."""
    events.clear()
    nameless = {"id": "wamid.nameless", "type": "text", "text": {"body": "hello?"}}

    assert dispatch_message(nameless, {}) == []

    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1
    assert "could not identify the sender" in failures[0].output
    events.clear()


def test_a_phone_number_wins_over_the_user_id_when_both_arrive():
    """Both back offices are searched by phone, task 33's web chat asks for a
    phone, and a BSUID dies with the business portfolio -- which this project has
    already changed once."""
    message, contact = _one(_hidden_number_payload("hi"))
    message = {**message, "from": "60129993001"}

    sender = _identify(message, contact)

    assert sender.key == "60129993001"
    assert sender.phone == "60129993001"
    assert sender.user_id == BSUID  # still recorded, just not what we file under


def test_the_username_does_not_overwrite_a_name_we_were_given():
    """A handle Meta lets them change tomorrow does not outrank what they told us
    they are called."""
    profile = user_store.get_or_create(BSUID)
    profile.display_name = "Kelvin Pang"

    _remember_identity(profile, Sender(key=BSUID, phone=None, user_id=BSUID, username="kelvin.p"))

    assert profile.display_name == "Kelvin Pang"
    assert profile.username == "kelvin.p"


# -- voice notes (task 36) -----------------------------------------------------
#
# A voice note becomes a text message before anything downstream sees it. That is
# the whole design: no branch in the model call, no branch in the history, no
# branch in the tools. What these tests guard is the seam -- that the words get
# in, that the audio does not, and that the ways it can come to nothing all leave
# the customer with an instruction and the console with a line.

VOICE_MIME = "audio/ogg; codecs=opus"


def _voice_message(phone: str, media_id: str = "media-voice-1", seq: int = 5) -> dict:
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "audio",
        "audio": {"id": media_id, "mime_type": VOICE_MIME, "voice": True},
    }


@contextmanager
def _hears(said: str):
    """Both hops a voice note takes: Meta hands over the bytes, a provider reads them."""
    media = whatsapp_media.Media(content=b"OggS-pretend-opus", mime_type=VOICE_MIME)
    with patch.object(whatsapp_media, "fetch_media", return_value=media) as fetch:
        with patch.object(transcribe, "transcribe", return_value=said) as heard:
            yield fetch, heard


def test_a_voice_note_reaches_the_model_as_the_sentence_that_was_spoken():
    """The acceptance criterion. A customer who speaks instead of typing has to
    get the same assistant, mid-sentence language switching and all."""
    phone = "60129994001"
    _in_conversation(phone)
    spoken = "Boleh tak you check ada stock tak, 那个 earbuds?"
    seen = {}

    def capture(bot, customer, history, image=None):
        seen["said"] = history[-1].content
        return "Let me check the stock."

    with _hears(spoken):
        with patch.object(llm, "get_reply", side_effect=capture):
            sent = dispatch_message(_voice_message(phone))

    assert seen["said"] == spoken
    assert [message["type"] for message in sent] == ["text"]


def test_the_words_are_what_gets_remembered_not_the_voice_note():
    """The model is shown this history again next turn, and it cannot listen to
    an audio id."""
    phone = "60129994002"
    _in_conversation(phone)

    with _hears("do you deliver to Penang"):
        with patch.object(llm, "get_reply", return_value="We do."):
            dispatch_message(_voice_message(phone))

    stored = user_store.get(phone)
    assert [m.content for m in stored.history] == ["do you deliver to Penang", "We do."]


def test_the_voice_note_is_fetched_by_the_id_on_the_audio_block():
    phone = "60129994003"
    _in_conversation(phone)

    with _hears("hello") as (fetch, heard):
        with patch.object(llm, "get_reply", return_value="Hi."):
            dispatch_message(_voice_message(phone, media_id="media-voice-42"))

    assert fetch.call_args.args[0] == "media-voice-42"
    # And the provider is handed the type Meta reported, not one we guessed.
    assert heard.call_args.args[1] == VOICE_MIME


def test_saying_menu_out_loud_starts_the_demo_over():
    """Downstream is not told the message was spoken, so every text path answers
    a voice note too -- including the one that is not a question."""
    phone = "60129994004"
    _in_conversation(phone)

    with _hears("Menu"):
        sent = dispatch_message(_voice_message(phone))

    assert [message["type"] for message in sent] == ["interactive"]
    assert user_store.get(phone).bot_id is None


def test_the_console_shows_the_sentence_the_bot_heard():
    """The customer hears nothing happen; the room watching the second screen has
    to see what was understood before it is acted on."""
    phone = "60129994005"
    _in_conversation(phone)
    events.clear()
    spoken = "我要买两个 fan, hantar ke Johor"

    with _hears(spoken):
        with patch.object(llm, "get_reply", return_value="Two fans to Johor."):
            dispatch_message(_voice_message(phone))

    voice = [e for e in events.since(0) if e.tool == "voice.transcribe"]
    assert [e.type for e in voice] == [events.TOOL_START, events.TOOL_END]
    assert voice[0].input["mime_type"] == VOICE_MIME
    assert voice[1].output == spoken
    assert voice[1].status == "ok"
    assert voice[1].duration_ms is not None
    events.clear()


def test_a_transcription_that_fails_asks_for_typing_and_says_why_on_the_console():
    phone = "60129994006"
    _in_conversation(phone)
    events.clear()
    media = whatsapp_media.Media(content=b"OggS", mime_type=VOICE_MIME)

    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        with patch.object(
            transcribe, "transcribe", side_effect=transcribe.TranscriptionError("quota exceeded")
        ):
            with patch.object(llm, "get_reply") as get_reply:
                sent = dispatch_message(_voice_message(phone))

    get_reply.assert_not_called()
    assert sent[0]["text"]["body"] == VOICE_UNREADABLE_MESSAGE
    ended = [e for e in events.since(0) if e.type == events.TOOL_END]
    assert ended[0].status == "error" and "quota exceeded" in ended[0].output
    events.clear()


def test_a_download_that_fails_is_answered_rather_than_thrown():
    """`fetch_media` raises for a file over the size cap as well as for a dead
    network, and both arrive here as a customer waiting on a reply."""
    phone = "60129994007"
    _in_conversation(phone)

    with patch.object(
        whatsapp_media, "fetch_media", side_effect=whatsapp_media.MediaTooLargeError("too big")
    ):
        sent = dispatch_message(_voice_message(phone))

    assert sent[0]["text"]["body"] == VOICE_UNREADABLE_MESSAGE


def test_a_clip_with_nothing_audible_never_becomes_an_empty_turn():
    """An empty transcript down the text path is an empty user message: the model
    is asked to answer nothing, and the turn would be recorded as if something had
    been said. It stops here, and the console says which of the two it was."""
    phone = "60129994008"
    _in_conversation(phone)
    events.clear()

    with _hears(""):
        with patch.object(llm, "get_reply") as get_reply:
            sent = dispatch_message(_voice_message(phone))

    get_reply.assert_not_called()
    assert sent[0]["text"]["body"] == VOICE_UNREADABLE_MESSAGE
    assert user_store.get(phone).history == []
    ended = [e for e in events.since(0) if e.type == events.TOOL_END]
    assert ended[0].status == "ok" and ended[0].output == "(nothing audible)"
    events.clear()


def test_an_audio_message_with_no_media_id_is_answered_without_a_download():
    phone = "60129994009"
    _in_conversation(phone)
    events.clear()
    no_id = {**_voice_message(phone), "audio": {"mime_type": VOICE_MIME}}

    with patch.object(whatsapp_media, "fetch_media") as fetch:
        sent = dispatch_message(no_id)

    fetch.assert_not_called()
    assert sent[0]["text"]["body"] == VOICE_UNREADABLE_MESSAGE
    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1 and "no media id" in failures[0].output
    events.clear()


def test_a_message_type_nobody_handles_is_still_answered_with_the_type_it_instead():
    """Text, voice and photos are handled. A sticker is not, and must not look
    like it was: the customer has to be told to type."""
    phone = "60129994010"
    _in_conversation(phone)
    sticker = {**_voice_message(phone), "type": "sticker", "sticker": {"id": "media-stk-1"}}

    sent = dispatch_message(sticker)

    assert sent[0]["text"]["body"] == UNSUPPORTED_TYPE_MESSAGE


# -- photos (task 14) ----------------------------------------------------------
#
# Unlike a voice note, a photo cannot be turned into text on the way in, so this
# is the one input that reaches the model as itself. The seam these guard: the
# bytes get in, the history gets the caption instead of the bytes, and each of
# the three ways a download comes to nothing leaves the customer with something
# to do and the console with a line saying which it was.

PHOTO_MIME = "image/jpeg"
PHOTO_BYTES = b"\xff\xd8\xff-pretend-a-jpeg"


def _photo_message(
    phone: str, media_id: str = "media-img-1", caption: str | None = None, seq: int = 7
) -> dict:
    image = {"id": media_id, "mime_type": PHOTO_MIME, "sha256": "abc"}
    if caption is not None:
        image["caption"] = caption
    return {"id": f"wamid.{phone}.{seq}", "from": phone, "type": "image", "image": image}


@contextmanager
def _sees(mime_type: str = PHOTO_MIME):
    media = whatsapp_media.Media(content=PHOTO_BYTES, mime_type=mime_type)
    with patch.object(whatsapp_media, "fetch_media", return_value=media) as fetch:
        yield fetch


def test_a_photo_reaches_the_model_as_an_image_alongside_its_caption():
    """The acceptance criterion. What the customer photographed is what the bot
    is asked about, and the caption travels with it rather than separately."""
    phone = "60129995001"
    _in_conversation(phone)
    seen = {}

    def capture(bot, customer, history, image=None):
        seen["said"] = history[-1].content
        seen["image"] = image
        return "Those are the SP-1001 earbuds."

    with _sees():
        with patch.object(llm, "get_reply", side_effect=capture):
            sent = dispatch_message(_photo_message(phone, caption="what model is this?"))

    assert seen["said"] == "[photo] what model is this?"
    assert seen["image"] == llm.Image(data=PHOTO_BYTES, media_type="image/jpeg")
    assert [message["type"] for message in sent] == ["text"]


def test_a_photo_with_no_caption_is_still_a_turn_and_not_an_empty_one():
    """Most photos arrive with nothing written under them. An empty user message
    is one the API refuses and the transcript cannot explain."""
    phone = "60129995002"
    _in_conversation(phone)
    seen = {}

    def capture(bot, customer, history, image=None):
        # Read inside the call: the reply is appended to this same list on the
        # way out, so by the time `call_args` is inspected the last turn is the
        # bot's, not the customer's.
        seen["said"] = history[-1].content
        return "A cracked earbud case."

    with _sees():
        with patch.object(llm, "get_reply", side_effect=capture):
            dispatch_message(_photo_message(phone))

    assert seen["said"] == "[photo]"


def test_the_caption_is_what_gets_remembered_not_the_picture():
    """History is persisted per customer and replayed on every later turn. A photo
    kept in it would be paid for in Redis once and in input tokens forever."""
    phone = "60129995003"
    _in_conversation(phone)

    with _sees():
        with patch.object(llm, "get_reply", return_value="A pair of earbuds."):
            dispatch_message(_photo_message(phone, caption="what is this?"))

    stored = user_store.get(phone)
    assert [m.content for m in stored.history] == ["[photo] what is this?", "A pair of earbuds."]


def test_the_photo_is_fetched_by_the_id_on_the_image_block():
    phone = "60129995004"
    _in_conversation(phone)

    with _sees() as fetch:
        with patch.object(llm, "get_reply", return_value="Seen."):
            dispatch_message(_photo_message(phone, media_id="media-img-42"))

    assert fetch.call_args.args[0] == "media-img-42"


def test_the_console_shows_the_file_arriving_with_its_type_and_size():
    """The customer sees only a pause. The room watching the second screen sees
    the download happen before anything is said about it."""
    phone = "60129995005"
    _in_conversation(phone)
    events.clear()

    with _sees():
        with patch.object(llm, "get_reply", return_value="Seen."):
            dispatch_message(_photo_message(phone))

    spans = [e for e in events.since(0) if e.tool == "image.download"]
    assert [e.type for e in spans] == [events.TOOL_START, events.TOOL_END]
    assert spans[0].input["mime_type"] == PHOTO_MIME
    assert spans[1].status == "ok"
    assert spans[1].output == f"image/jpeg, {len(PHOTO_BYTES)} bytes"
    assert spans[1].duration_ms is not None
    events.clear()


def test_a_photo_download_that_fails_is_answered_rather_than_thrown():
    """`fetch_media` raises for a file over the size cap as well as for a dead
    network, and both arrive here as a customer waiting on a reply."""
    phone = "60129995006"
    _in_conversation(phone)
    events.clear()

    with patch.object(
        whatsapp_media, "fetch_media", side_effect=whatsapp_media.MediaTooLargeError("too big")
    ):
        with patch.object(llm, "get_reply") as get_reply:
            sent = dispatch_message(_photo_message(phone))

    get_reply.assert_not_called()
    assert sent[0]["text"]["body"] == IMAGE_UNREADABLE_MESSAGE
    ended = [e for e in events.since(0) if e.type == events.TOOL_END]
    assert ended[0].status == "error" and "too big" in ended[0].output
    events.clear()


def test_a_format_the_model_cannot_read_never_becomes_an_api_call():
    """Sent as a TIFF, say. The 400 would arrive after the download was already
    paid for, and reach the customer as a dead bot rather than as an answer."""
    phone = "60129995007"
    _in_conversation(phone)
    events.clear()

    with _sees(mime_type="image/tiff"):
        with patch.object(llm, "get_reply") as get_reply:
            sent = dispatch_message(_photo_message(phone))

    get_reply.assert_not_called()
    assert sent[0]["text"]["body"] == IMAGE_UNREADABLE_MESSAGE
    ended = [e for e in events.since(0) if e.type == events.TOOL_END]
    assert ended[0].status == "error" and "image/tiff" in ended[0].output
    events.clear()


def test_an_image_message_with_no_media_id_is_answered_without_a_download():
    phone = "60129995008"
    _in_conversation(phone)
    events.clear()
    no_id = {**_photo_message(phone), "image": {"mime_type": PHOTO_MIME}}

    with patch.object(whatsapp_media, "fetch_media") as fetch:
        sent = dispatch_message(no_id)

    fetch.assert_not_called()
    assert sent[0]["text"]["body"] == IMAGE_UNREADABLE_MESSAGE
    failures = [e for e in events.since(0) if e.type == events.SEND_FAILED]
    assert len(failures) == 1 and "no media id" in failures[0].output
    events.clear()


def test_a_photo_captioned_menu_does_not_start_the_demo_over():
    """The marker earns its keep here: `menu` resets the demo, and a customer
    captioning a photo with it is asking about the photo, not for the list."""
    phone = "60129995009"
    _in_conversation(phone)

    with _sees():
        with patch.object(llm, "get_reply", return_value="That's our menu board."):
            sent = dispatch_message(_photo_message(phone, caption="menu"))

    assert [message["type"] for message in sent] == ["text"]
    assert user_store.get(phone).bot_id is not None
