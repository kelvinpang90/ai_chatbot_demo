"""N1: the round-1 handover guard keyed on the label, and task 19.1's closing
summary is sent with the default one -- so pressing 结束演示 during a handover
sends nothing while the endpoint reports success.
"""
from unittest.mock import patch

from app.services import handover, notify
from app.services.user_store import user_store


def _held(phone: str):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(phone))


def test_the_closing_summary_still_reaches_the_phone():
    phone = "60129990301"
    _held(phone)

    with patch.object(notify.whatsapp_media, "send_message") as send:
        notify.send_now(phone, "📋 刚才这 10 分钟里…")

    send.assert_called_once()
