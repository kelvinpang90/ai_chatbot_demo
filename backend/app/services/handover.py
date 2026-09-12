"""When a person takes the conversation off the bot, and when they give it back.

The answer to the last question anybody asks before buying this: "and when it
cannot cope?" The demo's answer is that the bot stops talking, a human types,
and the customer never sees the join -- which is why nothing here sends the
customer an announcement on the way in or out. The only message they get is the
one a person wrote.

Where the flag lives is the one decision worth reading twice. The plan put it in
`session_store`, and it is on the customer's record instead: `session_store` is
this process's own memory, and a redeploy mid-demo would drop the flag and set
the bot talking over whoever was mid-sentence on the second screen. The record is
in Redis and survives that.

The demo number is a pure Cloud API number with no WhatsApp Business App behind
it, so -- unlike the company's own service line -- there is no phone anybody can
pick up to answer it. The person types on the console. `routers/console.py` is
the other half of this.
"""
from __future__ import annotations

import logging
import time

from app.console import events
from app.services.user_store import user_store

logger = logging.getLogger(__name__)

# Drawn on the console as a tool span, the way every other thing worth watching
# is: the room sees the line appear the moment the bot goes quiet, which is the
# half of scene 3 that happens on the big screen rather than on the phone.
HANDOVER_TOOL = "handover"

# How long a takeover survives without the person doing anything.
#
# It exists because the first version had no ceiling at all -- the flag rode on
# the customer's record for seven days. The round-1 note called that an accepted
# edge, mitigated by the console banner; round two took that apart, because the
# banner is visible only to a console that is open, with the right token, on the
# day, and nobody is at one next week. Both of round one's other findings trace
# back to it.
#
# Measured from the last thing the PERSON did, not from when they took over. A
# ceiling on the whole takeover cuts off a colleague who is still mid-sentence at
# two hours and one minute, which is the wrong half to be strict with.
#
# And only the person's own actions count. A customer who keeps typing is not
# evidence that anybody is reading -- that is precisely the shape of the failure
# this ceiling exists for, a takeover nobody is attending and a customer being
# ignored rather than answered.
MAX_IDLE_SECONDS = 2 * 60 * 60

# What the customer is told when they ask for a person. Three languages, like
# every other line the model did not write -- and the only one either side of
# this sends automatically: going back to the bot says nothing at all, because a
# customer who is told "the robot is back" has been shown the join.
HANDED_OVER_MESSAGE = (
    "好的，我帮您转接同事，请稍等一下。 / "
    "Of course - I'm passing you to a colleague now, one moment. / "
    "Baik, saya sambungkan anda kepada rakan sekerja saya, sekejap ya."
)


def begin(profile, reason: str = "") -> bool:
    """Take this conversation off the bot. False if there is nobody on file.

    Takes the caller's own record object rather than a key, and that is not a
    convenience. The router is holding a copy of this customer for the length of
    the turn and saves it when the turn ends; a version of this that re-read the
    record, set the flag on that second copy and saved it would have the router
    write the first copy back over the top a moment later -- the flag gone, the
    bot answering, and nothing in any log to say why. Caught by
    `test_asking_for_a_person_hands_it_over_and_says_so_once` before it ever ran
    on a phone. Setting it on the object the caller already has is what makes the
    two writes agree.

    Already in a person's hands is not an error and not a second event: a
    customer who asks twice while waiting has not asked for anything new.
    """
    if profile is None:
        logger.warning("asked to hand over a customer who is not on file")
        return False
    if profile.handover_since:
        return True

    key_id = profile.key_id
    now = time.time()
    profile.handover_since = now
    # Taking it over is itself the first sign of life.
    profile.handover_active_at = now
    user_store.save(profile)
    events.emit(
        type=events.TOOL_START,
        tool=HANDOVER_TOOL,
        tool_use_id=key_id,
        input={"customer": profile.display_name or key_id, "reason": reason},
    )
    logger.info("handover started for %s: %s", key_id, reason or "(no reason given)")
    return True


def end(profile) -> bool:
    """Give it back to the bot. False if it never left. See `begin` for why this
    takes the record rather than a key.

    The customer is told nothing. They were never told a robot had them in the
    first place, and "the machine is back now" is the one sentence that would
    turn a seamless handover into a visible one.
    """
    if profile is None or not profile.handover_since:
        return False

    key_id = profile.key_id
    held_for = max(0, int(time.time() - profile.handover_since))
    profile.handover_since = 0.0
    profile.handover_active_at = 0.0
    user_store.save(profile)
    events.emit(
        type=events.TOOL_END,
        tool=HANDOVER_TOOL,
        tool_use_id=key_id,
        output=f"{profile.display_name or key_id}: back with the bot after {held_for}s",
        duration_ms=held_for * 1000,
        status="ok",
    )
    logger.info("handover ended for %s after %ss", key_id, held_for)
    return True


def touch(profile) -> None:
    """Record that the person holding this conversation is still here.

    Called when they send something, and by nothing else. The clock this feeds
    is the answer to "is anybody still reading?", and only their own actions are
    evidence of that -- see `MAX_IDLE_SECONDS`.
    """
    if profile is None or not profile.handover_since:
        return
    profile.handover_active_at = time.time()
    user_store.save(profile)


def active(profile) -> bool:
    """Whether this customer's conversation is in a person's hands right now.

    Lapsed takeovers read as false rather than being cleaned up here: this is
    asked on the hot path of every inbound message, and a read that writes is a
    read that can fail. The row is dropped from the console's list by `waiting`
    and the fields are cleared the next time anything saves the record.
    """
    if profile is None or not profile.handover_since:
        return False
    # Records written before the idle clock existed have no activity stamp; the
    # moment they were taken over is the best thing to measure from, which is
    # exactly what the previous version did for everybody.
    since = profile.handover_active_at or profile.handover_since
    return (time.time() - since) < MAX_IDLE_SECONDS


def waiting() -> list[dict]:
    """Everyone a person has taken over, for the console to show and answer.

    Read off the store rather than kept as a second list beside it: two places
    holding the same truth is how a customer ends up on a screen that says the
    bot is silent while the bot is answering them.
    """
    held = []
    for profile in user_store.everyone():
        if active(profile):
            held.append(
                {
                    "key_id": profile.key_id,
                    "display_name": profile.display_name,
                    "phone": profile.phone,
                    "bot_id": profile.bot_id,
                    "since": profile.handover_since,
                }
            )
    # Newest first. Ascending put the console's default -- `held[0]` -- on the
    # oldest one, which is whichever conversation somebody forgot to hand back
    # last week: every line the owner typed in front of the room would have gone
    # to a stranger. Found by a cold review of task 20.
    return sorted(held, key=lambda row: row["since"], reverse=True)
