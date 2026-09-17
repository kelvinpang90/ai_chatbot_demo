"""Task 38.1: the lines the model never writes go out in the customer's language.

Found on 2026-09-17 from a screenshot: a customer wrote "找人工客服" and got the
handover sentence in Chinese, English and Malay one after another. Each canned
line is now written three times over and sent once, in the language this
customer last wrote in -- or all three, when they have not written a word we
could read yet.
"""
from unittest.mock import patch

import anthropic
import httpx

from app.bots.registry import get_bot
from app.routers.whatsapp_webhook import (
    VOICE_UNREADABLE_MESSAGE,
    _say_instead_of_the_form,
    dispatch_message,
)
from app.services import handover, llm, transcribe, whatsapp, whatsapp_media
from app.services.user_store import UserProfile, user_store
from app.tools import realestate


def _customer(phone: str, bot_id: str = "retail", language: str | None = None):
    profile = user_store.get_or_create(phone)
    profile.bot_id = bot_id
    profile.language = language
    user_store.save(profile)
    return profile


def _text(phone: str, body: str, seq: int = 1) -> dict:
    return {"id": f"wamid.{phone}.{seq}", "from": phone, "type": "text", "text": {"body": body}}


def test_asking_for_a_person_in_chinese_is_answered_in_chinese_only():
    """The screenshot, reproduced."""
    phone = "60129996101"
    _customer(phone)

    with patch.object(llm, "get_reply", return_value="(the bot should not answer)"):
        (sent,) = dispatch_message(_text(phone, "找人工客服"))

    assert sent["text"]["body"] == handover.HANDED_OVER_MESSAGE.zh
    assert " / " not in sent["text"]["body"]


def test_what_they_write_is_filed_as_their_language_for_the_lines_with_no_words():
    phone = "60129996102"
    _customer(phone)

    with patch.object(llm, "get_reply", return_value="明天到。"):
        dispatch_message(_text(phone, "东西什么时候到？"))

    assert user_store.get(phone).language == "zh"


def test_a_word_that_says_nothing_does_not_move_a_known_language():
    phone = "60129996103"
    _customer(phone, language="ms")

    with patch.object(llm, "get_reply", return_value="👍"):
        dispatch_message(_text(phone, "ok"))

    assert user_store.get(phone).language == "ms"


def test_a_voice_note_that_will_not_transcribe_is_apologised_for_in_their_language():
    """No words of theirs on this turn at all: the record is the only way to know."""
    phone = "60129996104"
    _customer(phone, language="zh")
    media = whatsapp_media.Media(content=b"OggS", mime_type="audio/ogg; codecs=opus")
    voice = {
        "id": f"wamid.{phone}.2",
        "from": phone,
        "type": "audio",
        "audio": {"id": "media-voice-9", "mime_type": "audio/ogg; codecs=opus", "voice": True},
    }

    with patch.object(whatsapp_media, "fetch_media", return_value=media):
        with patch.object(transcribe, "transcribe", side_effect=transcribe.TranscriptionError("x")):
            (sent,) = dispatch_message(voice)

    assert sent["text"]["body"] == VOICE_UNREADABLE_MESSAGE.zh


def test_someone_we_have_never_read_still_gets_all_three():
    """A guess in the wrong language is worse than the long line."""
    phone = "60129996105"
    _customer(phone, language=None)
    sticker = {"id": f"wamid.{phone}.3", "from": phone, "type": "sticker", "sticker": {"id": "s"}}

    (sent,) = dispatch_message(sticker)

    assert len(sent["text"]["body"].split(" / ")) == 3


def test_the_apology_when_the_model_is_unreachable_is_in_their_language():
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    customer = UserProfile(key_id="60129996106", phone="60129996106", language="ms")

    with patch.object(llm, "get_tools", return_value=[]):
        with patch.object(llm._client.messages, "create", side_effect=error):
            reply = llm.get_reply(get_bot("hotel"), customer, history=[])

    assert reply == llm.FALLBACK_REPLY.ms


def test_a_refused_booking_form_is_asked_for_again_in_their_language():
    phone = "60129996107"
    _customer(phone, bot_id="realestate", language="en")
    form = whatsapp.build_flow_message(phone, "b", "1122334455", "tok", "Book", realestate.SCREEN)

    with patch.object(whatsapp, "send_raw") as send_raw:
        _say_instead_of_the_form(
            form, realestate.UNDELIVERED_FORM_MESSAGE, whatsapp.WhatsAppSendError("no")
        )

    (payload,) = [call.args[0] for call in send_raw.call_args_list]
    assert payload["text"]["body"] == realestate.UNDELIVERED_FORM_MESSAGE.en
    assert user_store.get(phone).history[-1].content == realestate.UNDELIVERED_FORM_MESSAGE.en
