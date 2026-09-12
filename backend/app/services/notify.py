"""Messages the bot sends because something happened, not because it was asked.

Every other message this service sends is a reply: an inbound message arrives,
`dispatch_message` builds payloads, the caller sends them. A push has no request
to reply to -- the customer's phone buzzes while they are doing something else --
which is why this is the one path that sends itself rather than handing payloads
back. `whatsapp_media.send_message` exists for exactly this caller.

The queue is the outbox's shape and for the outbox's reason: a tool knows that
something worth announcing just happened, and does not know who to announce it
to. So a tool leaves a `Push` here, and the router -- the one place that decides
who gets written to -- dispatches it against the number the message came from.

Scheduled with a plain `threading.Timer`, which is the same demo-scale bargain
`session_store` makes: one process, no persistence, and a restart forgets
whatever had not fired yet. A push that a restart swallowed is a phone that did
not buzz, not an order that went missing.

⚠️ On the gateway path (`routers/internal_whatsapp.py`) a push still sends
itself, using this service's own WhatsApp credentials rather than the gateway's.
That is correct for the demo number, which has talked to Meta directly since
2026-08-30, and would need revisiting for any downstream demo that does not.
"""
from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar
from typing import NamedTuple

from app.console import events
from app.services import audit, handover, whatsapp, whatsapp_media
from app.services.user_store import user_store

logger = logging.getLogger(__name__)

# WhatsApp carries a free-form message only within 24 hours of the customer's
# last one. Past that, an approved template or nothing -- anything else is an API
# error the customer never sees. docs/whatsapp-templates.md has the two we
# submitted and the rules that shaped them.
CUSTOMER_SERVICE_WINDOW_SECONDS = 24 * 60 * 60

# The template names and the order of their {{n}} slots are a contract with
# docs/whatsapp-templates.md. Change one and the other has to change with it, or
# the send is a Cloud API error and the phone stays quiet.
ORDER_CONFIRMED = "order_confirmed"
ORDER_SHIPPED = "order_shipped"
# Templates are approved per language, and there is no language on the customer
# record to pick one by: `UserProfile.language` exists and nothing has ever
# written to it. So a template goes out in English. The free-form path below is
# under no such constraint and carries all three.
TEMPLATE_LANGUAGE = "en"

# What the console calls a push, so the second screen shows the thing the
# customer's phone is about to do -- which in scene 3 is the whole point, because
# the room needs to see that nobody typed it. Same span shape as image.download
# and voice.transcribe, so the front end learns no new event type.
PUSH_TOOL = "notify.push"
# And what it calls a line a person typed on the console. A separate label, not
# a separate mechanism: the console span, the history entry and the audit row are
# all the same machinery -- what differs is that the room can see at a glance
# which of the two happened.
HUMAN_TOOL = "human.reply"


class Template(NamedTuple):
    """An approved template and the values for its {{n}} slots, in order."""

    name: str
    params: tuple[str, ...]

    def build(self, to: str) -> dict:
        return whatsapp.build_template_message(to, self.name, TEMPLATE_LANGUAGE, self.params)


class Push(NamedTuple):
    """Something to tell the customer a little after this turn is over.

    Both wordings are carried because which one goes out is not known when the
    push is queued: it depends on how much of the 24-hour window is left by the
    time the timer fires. `template` may be None, which means this push is worth
    sending inside the window and not worth a template outside it.
    """

    delay_seconds: float
    text: str
    template: Template | None = None


# Per conversation, not per process: replies run in FastAPI's sync threadpool and
# two customers can be mid-answer at the same moment. None rather than an empty
# list, and the distinction is load-bearing -- see `available`.
_pending: ContextVar[list[Push] | None] = ContextVar("notify_pending", default=None)


def begin() -> None:
    """Open a queue for one inbound message. Call before the model runs."""
    _pending.set([])


def close() -> None:
    """Drop the queue. For tests -- see `outbox.close` for why production does not
    need it and a shared test context does."""
    _pending.set(None)


def available() -> bool:
    """Whether a queued push would ever actually be sent.

    Only the WhatsApp path opens a queue. The web chat has no phone to buzz, so a
    tool has to be able to tell that it is not in a conversation that can be
    followed up -- the same honesty `outbox.available` exists for.
    """
    return _pending.get() is not None


def add(push: Push) -> bool:
    """Queue something to say later. False if nothing will ever send it."""
    pending = _pending.get()
    if pending is None:
        logger.warning("no push queue open, dropping a %s-second follow-up", push.delay_seconds)
        return False
    pending.append(push)
    return True


def dispatch(to: str) -> list[threading.Timer]:
    """Start the clock on everything queued this turn, emptying the queue.

    The window is stamped here rather than read off the customer record at send
    time. `UserProfile.last_seen` looks like the right source and is not: it is
    rewritten on every save, including the ones the bot makes after its own
    replies, so it says when we last touched the record and not when the customer
    last wrote. Stamping it here is exact -- an inbound message is being handled
    at this moment, so the window is open now -- and it errs the safe way for
    anything that happens afterwards: a customer who writes again only widens the
    window, so the worst this can do is send a template where a free-form message
    would have been allowed, which still arrives.
    """
    pending = _pending.get()
    if not pending:
        return []
    _pending.set([])

    window_opened_at = time.time()
    timers = []
    for push in pending:
        timer = threading.Timer(push.delay_seconds, _send, args=(to, push, window_opened_at))
        # So a shutdown is not held open by a follow-up nobody is waiting for.
        timer.daemon = True
        timer.start()
        timers.append(timer)
    return timers


def send_now(to: str, text: str, *, label: str = PUSH_TOOL, source: str = audit.TEXT) -> None:
    """Say something to this customer immediately, with no clock in between.

    For a push somebody asked for rather than one an event produced: the closing
    summary a person throws at the end of a demo (task 19.1). Everything else is
    the timed path's -- the console span, the history entry, the audit row -- so
    the message a human sent and one the bot sent look alike where it matters.

    The 24-hour window is stamped as now, which is a statement about when this is
    used rather than a check: the button is pressed while the room is still in
    the room. Pressed the next morning instead, Meta refuses the send and it
    lands on the console as a failure -- which is the right way round, because
    the alternative is a summary that silently went nowhere.
    """
    # `unattended=False`: somebody is pressing a button. Whatever a handover
    # means for the bot's own follow-ups, it does not mean swallowing the
    # thing a person just asked to send.
    _send(
        to,
        Push(delay_seconds=0, text=text),
        window_opened_at=time.time(),
        label=label,
        source=source,
        unattended=False,
    )


def _payload_for(to: str, push: Push, window_opened_at: float) -> dict | None:
    """The message to send, or None if there is nothing this channel will carry."""
    if time.time() - window_opened_at < CUSTOMER_SERVICE_WINDOW_SECONDS:
        return whatsapp.build_text_message(to, push.text)
    if push.template is None:
        logger.warning("the 24h window closed and %s has no template; dropping it", to)
        return None
    return push.template.build(to)


def _send(
    to: str,
    push: Push,
    window_opened_at: float,
    *,
    label: str = PUSH_TOOL,
    source: str = audit.TEXT,
    # Whether a timer started this rather than a person. Only the unattended kind
    # is dropped when a colleague has the conversation.
    unattended: bool = True,
) -> None:
    """Deliver one push. Runs on a timer thread, long after its turn ended.

    Nothing above catches for this one -- there is no request left to fail, and
    an exception on a timer thread is a traceback nobody reads. So it is caught
    here and said out loud on the console, where the person watching the second
    screen is the only one who can notice.
    """
    span = f"{to}:{int(time.time())}"
    started = time.monotonic()
    try:
        # Checked at the moment it fires, not when it was queued. The order that
        # queued this push is a minute old by now, and in that minute the
        # customer may have asked for a person -- at which point "your order is
        # on its way" arrives on top of whatever the colleague is typing. Found
        # by a cold review of task 20, which called it the worst shape of the
        # six: the others are the bot answering, this one is the bot
        # interrupting. A push a person swallowed is not resent afterwards; by
        # then it is not news.
        #
        # Only the bot's own. The first version of this guard keyed on the label
        # and swallowed task 19.1's closing summary with it -- the operator
        # pressed 结束演示, the console said it had gone to Kelvin, and the phone
        # got nothing. Round two of the same review caught it. What separates the
        # two is not who they are addressed to but who started them: a timer, or
        # a person's finger.
        if unattended and handover.active(user_store.get(to)):
            logger.info("dropping a queued push to %s: a person has the conversation", to)
            return
        payload = _payload_for(to, push, window_opened_at)
        if payload is None:
            return
        events.emit(
            type=events.TOOL_START,
            tool=label,
            tool_use_id=span,
            input={"to": to, "kind": payload.get("type", "")},
        )
        whatsapp_media.send_message(payload)
        events.emit(
            type=events.TOOL_END,
            tool=label,
            tool_use_id=span,
            output=push.text,
            duration_ms=int((time.monotonic() - started) * 1000),
            status="ok",
        )
        _remember(to, push.text, source)
    except Exception as failure:
        logger.exception("could not push a follow-up to %s", to)
        events.emit(
            type=events.SEND_FAILED,
            tool=label,
            tool_use_id=span,
            output=f"{type(failure).__name__}: {failure}",
            status="error",
        )


def _remember(to: str, text: str, source: str = audit.TEXT) -> None:
    """Put the push into the customer's history and into the audit log.

    Without it the model is asked "when?" about a message it cannot see itself
    having sent, and the transcript has a hole exactly where the customer's phone
    buzzed -- which is the moment anyone reading it back wants to find.

    The text filed is ours even when a template went out instead. Meta holds the
    approved wording and we hold this one; they say the same thing, and a
    transcript that said "[template order_confirmed]" would be worse to read than
    a sentence that is a paraphrase of what arrived.
    """
    profile = user_store.get(to)
    if profile is None:
        return
    profile.add_message("assistant", text)
    user_store.save(profile)
    # A turn of its own: the one this push was queued in closed a long time ago,
    # and a push belongs to the conversation rather than to a reply.
    audit.begin_for(profile, audit.WHATSAPP)
    try:
        audit.record_message("assistant", text, source)
    finally:
        audit.close()
