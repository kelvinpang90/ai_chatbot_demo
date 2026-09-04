import itertools
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.console import events
from app.main import app
from app.routers.whatsapp_webhook import (
    Sender,
    _extract_messages,
    _handle_incoming_message,
    _identify,
    _remember_identity,
    _resolve_quick_question,
    _truncate,
    dispatch_message,
)
from app.services import llm, outbox, whatsapp
from app.services.user_store import user_store

client = TestClient(app)


def test_truncate_leaves_short_text_untouched():
    assert _truncate("hello", 24) == "hello"


def test_truncate_shortens_long_text_with_ellipsis():
    text = "a" * 30
    result = _truncate(text, 24)
    assert len(result) == 24
    assert result.endswith("…")


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


def _list_reply(phone: str, option_id: str, seq: int = 9) -> dict:
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": {"id": option_id}},
    }


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

    def capture(bot, customer, history):
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

    def capture(bot, customer, history):
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
