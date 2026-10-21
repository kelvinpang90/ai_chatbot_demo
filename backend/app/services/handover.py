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

from app.config import settings
from app.console import events
from app.services import crm_events
from app.services.language import Localized
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
#
# The number itself lives in `settings.handover_idle_seconds` (env
# HANDOVER_IDLE_SECONDS) so the VPS can change it with a restart rather than a
# deploy. Read at each call rather than bound to a module constant, so a test
# can move it without reloading this module.

# What the customer is told when they ask for a person, in the language they
# asked in (task 38.1: "找人工客服" used to get all three) -- and the only line
# either side of this sends automatically: going back to the bot says nothing at
# all, because a customer who is told "the robot is back" has been shown the join.
HANDED_OVER_MESSAGE = Localized(
    zh="好的，我帮您转接同事，请稍等一下。",
    en="Of course - I'm passing you to a colleague now, one moment.",
    ms="Baik, saya sambungkan anda kepada rakan sekerja saya, sekejap ya.",
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
    A takeover that has lapsed is not in anybody's hands, though, even with
    `handover_since` still on the record (see `active`): asking again starts a
    new one. Task 40.0 -- the old check read the stale field and did nothing.
    """
    if profile is None:
        logger.warning("asked to hand over a customer who is not on file")
        return False
    if active(profile):
        return True
    _start(profile, reason)
    return True


def _start(profile, reason: str) -> bool:
    """Take it over. Returns whether that reached the store (see `hold`)."""
    key_id = profile.key_id
    now = time.time()
    profile.handover_since = now
    # Taking it over is itself the first sign of life.
    profile.handover_active_at = now
    stored = user_store.save(profile)
    _tell_crm(profile, now, stored)
    events.emit(
        type=events.TOOL_START,
        tool=HANDOVER_TOOL,
        tool_use_id=key_id,
        input={"customer": profile.display_name or key_id, "reason": reason},
        # Named outright: this is usually pressed on the console, where nobody
        # is being served and the context would file it under no one.
        key_id=key_id,
    )
    logger.info("handover started for %s: %s", key_id, reason or "(no reason given)")
    return stored


def end(profile) -> bool:
    """Give it back to the bot. False if it never left. See `begin` for why this
    takes the record rather than a key.

    The customer is told nothing. They were never told a robot had them in the
    first place, and "the machine is back now" is the one sentence that would
    turn a seamless handover into a visible one.
    """
    if profile is None or not profile.handover_since:
        return False
    _finish(profile, time.time())
    return True


def _finish(profile, now: float) -> bool:
    """Give it back as of `now`. Returns whether that reached the store."""
    key_id = profile.key_id
    held_for = max(0, int(now - profile.handover_since))
    profile.handover_since = 0.0
    profile.handover_active_at = 0.0
    stored = user_store.save(profile)
    _tell_crm(profile, now, stored)
    events.emit(
        type=events.TOOL_END,
        tool=HANDOVER_TOOL,
        tool_use_id=key_id,
        output=f"{profile.display_name or key_id}: back with the bot after {held_for}s",
        duration_ms=held_for * 1000,
        status="ok",
        key_id=key_id,
    )
    logger.info("handover ended for %s after %ss", key_id, held_for)
    return stored


def touch(profile) -> None:
    """Record that the person holding this conversation is still here.

    Called when they send something, and by nothing else. The clock this feeds
    is the answer to "is anybody still reading?", and only their own actions are
    evidence of that -- see `settings.handover_idle_seconds`.
    """
    if profile is None or not profile.handover_since:
        return
    _renew(profile)


def _renew(profile) -> bool:
    profile.handover_active_at = time.time()
    stored = user_store.save(profile)
    _tell_crm(profile, profile.handover_active_at, stored)
    return stored


def hold(profile, reason: str = "") -> bool:
    """Start a takeover, or renew the one in progress, for a person replying
    from outside the console -- the CRM (task 41.3).

    `begin` alone would not do: on a conversation already in a person's hands it
    returns without touching anything, and a reply has to push the expiry out.
    Returns whether the change reached the store everyone reads. A caller that
    reports the takeover to another system must not report one that did not:
    it lives in this process's memory for thirty seconds and is then read back
    from Redis as it was (task 42.1, round 3 of its cold review).
    """
    return _renew(profile) if active(profile) else _start(profile, reason)


def release(profile, at: float) -> bool:
    """Give a held conversation back as of `at`, for the CRM's hand-back.

    `at` is the caller's: the record keeps nothing once it is cleared, and the
    hand-back answers with the same moment the event carries (task 42.1).
    Returns whether that reached the store, as `hold` does.
    """
    return _finish(profile, at)


def crm_state(profile) -> dict:
    """This customer's takeover as the CRM is told it: `active` and `expires_at`."""
    if profile.handover_since:
        expires_at = crm_events.utc(profile.handover_active_at + settings.handover_idle_seconds)
        return {"active": True, "expires_at": expires_at}
    return {"active": False, "expires_at": None}


def _tell_crm(profile, at: float, stored: bool) -> None:
    """Queue this customer's takeover state for the CRM (task 40.2).

    Called where the state really changes -- a takeover starting, being renewed,
    ending -- and nowhere else. A takeover that lapses is not pushed: nothing
    runs at that moment (see `active`), and the contract has the CRM read
    `expires_at` rather than wait to be told.

    `at` is the moment of the change, the one already written on the record.
    Letting the queue read its own clock instead was a second reading that
    could land in the next second -- and a CRM send answers with this moment
    and the event must carry the same one (task 41.3, contract section 5).

    Only what reached Redis is told: `stored` is `user_store.save`'s answer for
    this very write. A save that fell back lands in memory alone; the copy in
    Redis is unchanged and is what everyone reads again thirty seconds later.
    Telling the CRM about the memory copy -- "handed back", say, for a visitor
    Redis still holds -- leaves it showing a state the bot will not be in, with
    no error anywhere to retry. The event queue has its own Redis client, so it
    can succeed where the save failed. Found by round 2 of task 42.1's cold
    review; round 3 had it asked of this write rather than of `offline()`,
    which another thread's failure can flip after a write that did land.
    """
    if not stored:
        logger.error(
            "crm events: %s's takeover changed in memory only, Redis is offline; not telling the CRM",
            profile.key_id,
        )
        return
    crm_events.enqueue(
        "handover_changed", crm_events.visitor_for(profile), occurred_at=at, handover=crm_state(profile)
    )


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
    return (time.time() - since) < settings.handover_idle_seconds


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
