"""A1, the root the confrontation pass pressed on: the flag has no ceiling.

Both round-one findings trace back to it -- a message that muted the bot muted
it for seven days, and the console's default target was whichever conversation
somebody forgot to hand back. The mitigation the round-one record claimed (the
console banner) is visible only to somebody with a console open, on the day.
"""
import time

from app.services import handover
from app.services.user_store import user_store


def test_a_takeover_nobody_ended_lapses_on_its_own():
    phone = "60129990501"
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(phone))

    stale = user_store.get(phone)
    # Two hours is the ceiling the fix introduces; this is well past any of it.
    stale.handover_since = time.time() - 8 * 60 * 60
    user_store.save(stale)

    assert handover.active(user_store.get(phone)) is False
    assert [row["key_id"] for row in handover.waiting()] == []
