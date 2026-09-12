"""P1-2: six paths let the bot talk while a person holds the conversation.

Five return before the guard inside `_handle_text_message`, and what they send
is the set of lines that announce there is a bot at all. The sixth is a push
queued before the handover, which fires during it.
"""
import time
from unittest.mock import patch

import pytest

from app.routers.whatsapp_webhook import dispatch_message
from app.services import handover, notify
from app.services.user_store import user_store
from app.session_store import session_store


def _held(phone: str):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(phone))
    return profile


@pytest.mark.parametrize(
    "block",
    [
        {"type": "sticker", "sticker": {"id": "media-stk-1"}},
        {"type": "audio", "audio": {"mime_type": "audio/ogg"}},
        {"type": "image", "image": {"mime_type": "image/jpeg"}},
        {"type": "document", "document": {"mime_type": "application/pdf"}},
    ],
)
def test_the_bot_does_not_apologise_over_a_person(block):
    phone = "60129990101"
    _held(phone)

    sent = dispatch_message({"id": f"wamid.{phone}.{block['type']}", "from": phone, **block})

    assert sent == [], sent


def test_the_daily_cap_does_not_interrupt_a_person():
    phone = "60129990102"
    _held(phone)

    with patch.object(session_store, "check_and_increment_daily_count", return_value=False):
        sent = dispatch_message(
            {"id": f"wamid.{phone}.2", "from": phone, "type": "text", "text": {"body": "hi"}}
        )

    assert sent == [], sent


def test_a_push_queued_before_the_handover_does_not_fire_during_it():
    phone = "60129990103"
    _held(phone)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify._send(phone, notify.Push(delay_seconds=0, text="您的订单已确认"), time.time())

    send.assert_not_called()
