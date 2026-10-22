"""Conversation events for the CRM: queued in Redis, sent one at a time, signed.

Phase one of "demo number, many agents" (tasks/todo.md batch 08): every
WhatsApp visitor on the demo number shows up in the CRM's inbox. The contract is
`docs/chatbot-events.md` in acuven_crm_demo -- one event per request to
`POST /internal/chatbot/events`, HMAC-signed, delivered in order.

Not to be confused with `outbox.py`, which carries the attachments that ride
along with one reply. This is a queue of events, and nothing else.

Two promises, and everything below serves one of them:

1. Nothing here can hurt the customer's conversation. `enqueue` is called from
   the code that answers them, so it never raises, and when the switch is off it
   does not so much as open a Redis connection.
2. Order. The CRM applies a visitor's events in the order they arrive, so the
   head of the queue is retried until the CRM has it -- the second event is not
   looked at before then. That holds only with one consumer, which is the same
   single-process assumption `session_store` has always made.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services import phone
from app.services.user_store import user_store

logger = logging.getLogger(__name__)

QUEUE_KEY = "chat:crm_events"
# Events the CRM said were malformed (422). Kept, never retried, never expired:
# someone reads them and `DEL`s the key by hand.
DEAD_KEY = "chat:crm_events:dead"

INITIAL_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 300.0
REQUEST_TIMEOUT_SECONDS = 10.0
IDLE_POLL_SECONDS = 1.0
# A CRM that is down stays down for a while, and the backoff tops out at five
# minutes; one ERROR line per attempt would bury every other log line. The first
# failure says so at once, then one reminder per this many seconds.
ALERT_EVERY_SECONDS = 600.0
# How much of the CRM's answer to keep beside a dead event.
DEAD_RESPONSE_CHARS = 500

# What the CRM may say inside a 200. Anything else is still a 200 -- the CRM has
# the event -- but means the two sides have drifted apart.
KNOWN_RESULTS = {"stored", "duplicate", "ignored"}

# What `deliver_one` did.
EMPTY = "empty"
DELIVERED = "delivered"
DEAD = "dead"
RETRY = "retry"

# Redis is one hop away on data_net. Same reasoning as `user_store`: `enqueue`
# runs where a customer is waiting, so a Redis that is down must cost a second,
# not a default multi-second timeout.
CONNECT_TIMEOUT_SECONDS = 1.0
OPERATION_TIMEOUT_SECONDS = 1.0
# And once a write has failed, `enqueue` stops paying that second for this long
# -- the same breaker `user_store` keeps on the same Redis. Without it a Redis
# that is down cost a second per event, and one reply queues an event between
# each of its messages: the greeting arrived, then its buttons a second later,
# on the thread the customer is waiting on. Found by the cold review of task
# 40.2. Events in the window are dropped, as they would be anyway with nowhere
# to put them; each drop is logged.
REDIS_RETRY_AFTER_SECONDS = 30.0


def _default_client(url: str):
    import redis

    return redis.Redis.from_url(
        url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=OPERATION_TIMEOUT_SECONDS,
        decode_responses=True,
    )


# Swapped out by tests, the way `UserStore` takes a `client_factory`.
_client_factory = _default_client
_client = None
_thread: threading.Thread | None = None
_offline_until = 0.0


def _now() -> float:
    return time.time()


def utc(seconds: float) -> str:
    """A moment as the contract spells it: UTC, to the second, with a Z."""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _missing_configuration() -> str | None:
    """Why a switched-on queue cannot run, or None if it can."""
    if not settings.redis_url:
        return "REDIS_URL is empty"
    if not settings.crm_events_secret:
        return "CRM_EVENTS_SECRET is empty"
    return None


def enabled() -> bool:
    return settings.crm_events_enabled and _missing_configuration() is None


def _redis():
    global _client
    if _client is None:
        _client = _client_factory(settings.redis_url)
    return _client


def visitor(phone_number: str | None, bsuid: str | None, profile_name: str | None) -> dict:
    """Who an event is about, in the shape the contract asks for.

    A BSUID handed over as the number -- a delivery status only carries one
    recipient field -- is moved to where it belongs, and "which of the two is
    this" is `phone.is_bsuid`'s call, not a rule of this module's own. Blanks
    become None. Whether there is anything left to identify the visitor by is
    `enqueue`'s check, so a caller cannot skip it.
    """
    if phone_number and phone.is_bsuid(phone_number):
        bsuid = bsuid or phone_number.strip()
        phone_number = None
    return {
        "phone": phone_number or None,
        "bsuid": bsuid or None,
        "profile_name": profile_name or None,
    }


def enqueue(event_type: str, who: dict, *, occurred_at: float | None = None, **fields) -> None:
    """Queue one event for the CRM. Never raises; does nothing when switched off.

    `occurred_at` is when it happened (Unix seconds) -- Meta's own timestamp for
    a customer's message -- and defaults to now. `fields` are the type's own
    keys from the contract: `message`, `bot_id`, `handover`, `status`.

    The event is stored as the exact string that will later be sent and signed,
    so what the CRM verifies is byte for byte what was queued.
    """
    global _offline_until
    if not enabled():
        return
    try:
        if not (who.get("phone") or who.get("bsuid")):
            logger.error("crm events: dropped a %s event with neither a phone nor a bsuid", event_type)
            return
        event = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "occurred_at": utc(_now() if occurred_at is None else occurred_at),
            "visitor": who,
            **fields,
        }
        if _now() < _offline_until:
            logger.error("crm events: dropped a %s event, Redis failed a moment ago", event_type)
            return
        try:
            _redis().rpush(QUEUE_KEY, json.dumps(event, ensure_ascii=False))
        except Exception:
            _offline_until = _now() + REDIS_RETRY_AFTER_SECONDS
            raise
    except Exception:
        logger.exception("crm events: could not queue a %s event", event_type)


def visitor_for(profile) -> dict:
    """The visitor an event is about, from their customer record."""
    return visitor(profile.phone, profile.user_id, profile.username)


# How each kind of interactive message is marked in the CRM's inbox: the CRM
# only shows text, and "[list] Pick a demo" says what the customer was shown.
_INTERACTIVE_MARKERS = {"list": "[list]", "button": "[buttons]", "flow": "[form]"}


def outbound_body(payload: dict, text: str | None = None) -> str:
    """What one message we sent says, as the line the CRM's inbox shows.

    Public because the console files the demo list with it too (task 43): the
    two are read side by side, and the same message should read the same.
    """
    if text is not None:
        return text
    kind = payload.get("type")
    if kind == "text":
        return (payload.get("text") or {}).get("body", "")
    if kind == "interactive":
        interactive = payload.get("interactive") or {}
        marker = _INTERACTIVE_MARKERS.get(interactive.get("type"), "[interactive]")
        said = (interactive.get("body") or {}).get("text", "")
        return f"{marker} {said}".strip()
    if kind == "document":
        document = payload.get("document") or {}
        return " ".join(
            part for part in ("[document]", document.get("filename"), document.get("caption")) if part
        )
    return f"[{kind}]"


def outbound(kind: str, payload: dict, response, text: str | None = None) -> None:
    """Queue a message we just sent: `ai_reply` or `console_reply`. Never raises.

    Called only after Meta accepted the send, because the CRM files a message by
    the id Meta gave it -- and a message the customer never received does not
    belong in anybody's inbox. `text` overrides what is read off the payload; a
    push sent as a template passes the sentence we keep for it, which is the one
    `notify._remember` files too.

    `bot_id` is the demo the customer is in at the moment of sending, None
    before they have picked one; a console reply has none at all.
    """
    if not enabled():
        return
    try:
        try:
            wa_message_id = response.json()["messages"][0]["id"]
        except Exception:
            logger.warning("crm events: Meta's answer to a %s carried no message id; not queued", kind)
            return
        to = str(payload.get("to") or payload.get("recipient") or "")
        profile = user_store.get(to) if to else None
        who = visitor_for(profile) if profile else visitor(to, None, None)
        fields = {"message": {"wa_message_id": wa_message_id, "body": outbound_body(payload, text)}}
        if kind == "ai_reply":
            fields["bot_id"] = profile.bot_id if profile else None
        enqueue(kind, who, **fields)
    except Exception:
        logger.exception("crm events: could not queue a %s", kind)


def _sign(timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        settings.crm_events_secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


class _Alarm:
    """Says a delivery is failing: at once, then every ten minutes, then once when it stops.

    Logs only, on purpose (Kelvin, 2026-10-12): the director's console is on a
    screen the customer is looking at, and a line saying the CRM sync broke in
    the middle of a demo would be the incident. Found with
    `docker logs ai_chatbot_backend 2>&1 | grep crm_events`.
    """

    def __init__(self) -> None:
        self.failures = 0
        self.last_raised: float | None = None

    def failed(self, message: str, *args) -> None:
        self.failures += 1
        now = _now()
        if self.last_raised is None or now - self.last_raised >= ALERT_EVERY_SECONDS:
            logger.error("crm events: " + message + " (%d failed attempts so far)", *args, self.failures)
            self.last_raised = now

    def cleared(self) -> None:
        if self.failures:
            logger.info("crm events: delivering again after %d failed attempts", self.failures)
        self.failures = 0
        self.last_raised = None


_alarm = _Alarm()


def deliver_one(client, http: httpx.Client) -> str:
    """Send the event at the head of the queue, once. Returns what happened.

    The head is read, not taken: it leaves the queue only once the CRM has it
    (200) or has said it never will (422, into the dead letters). Every other
    answer -- 401, 503, a 404 from a mistyped URL, no answer at all -- leaves it
    where it is to be tried again, because each of those is fixed by fixing
    configuration and the event should still be there when it is.
    """
    raw = client.lindex(QUEUE_KEY, 0)
    if raw is None:
        return EMPTY

    body = raw.encode("utf-8")
    # The moment of sending, not of queueing: the CRM refuses a timestamp more
    # than 300 seconds off its clock, so an event that waited out a five-minute
    # backoff, signed with when it was queued, would be refused forever.
    timestamp = int(_now())
    headers = {
        "Content-Type": "application/json",
        "X-Acuven-Timestamp": str(timestamp),
        "X-Acuven-Signature": _sign(timestamp, body),
    }
    try:
        # `content=`, never `json=`: httpx would serialise the event again, and
        # the bytes signed would no longer be the bytes sent.
        response = http.post(settings.crm_events_url, content=body, headers=headers)
    except Exception as failure:
        _alarm.failed("could not reach the CRM: %r", failure)
        return RETRY

    if response.status_code == 200:
        try:
            result = response.json().get("result")
        except Exception:
            result = None
        if result not in KNOWN_RESULTS:
            logger.warning("crm events: the CRM took an event but answered %r", response.text[:DEAD_RESPONSE_CHARS])
        client.lpop(QUEUE_KEY)
        _alarm.cleared()
        return DELIVERED

    if response.status_code == 422:
        dead = {
            "event": raw,
            "status": response.status_code,
            "response": response.text[:DEAD_RESPONSE_CHARS],
            "failed_at": utc(_now()),
        }
        # Filed before it is removed: dying between the two calls costs a
        # second identical dead letter, never the event.
        client.rpush(DEAD_KEY, json.dumps(dead, ensure_ascii=False))
        client.lpop(QUEUE_KEY)
        logger.error(
            "crm events: the CRM rejected an event as malformed, moved to %s: %s",
            DEAD_KEY,
            response.text[:DEAD_RESPONSE_CHARS],
        )
        _alarm.cleared()
        return DEAD

    if response.status_code == 401:
        _alarm.failed(
            "the CRM refused the signature (401) -- check that CRM_EVENTS_SECRET matches "
            "the CRM's CHATBOT_EVENTS_SECRET and that both clocks are right"
        )
    else:
        _alarm.failed("the CRM answered %d: %s", response.status_code, response.text[:200])
    return RETRY


class Backoff:
    """2, 4, 8 ... seconds between attempts at the same event, never past 300."""

    def __init__(self) -> None:
        self._delay = 0.0

    def failed(self) -> float:
        self._delay = min(max(self._delay * 2, INITIAL_BACKOFF_SECONDS), MAX_BACKOFF_SECONDS)
        return self._delay

    def reset(self) -> None:
        self._delay = 0.0


def run_forever(client=None, http: httpx.Client | None = None, sleep=time.sleep) -> None:
    """The consumer. Runs on its own thread until the process exits.

    Anything unexpected -- Redis gone, a bug -- is logged and waited out like a
    failed delivery; the thread itself never dies, because nothing would start
    it again until the next deploy.
    """
    http = http or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
    backoff = Backoff()
    while True:
        try:
            outcome = deliver_one(client or _redis(), http)
        except Exception as failure:
            _alarm.failed("the delivery loop failed: %r", failure)
            outcome = RETRY
        if outcome == RETRY:
            delay = backoff.failed()
            logger.info("crm events: retrying in %.0f seconds", delay)
            sleep(delay)
            continue
        backoff.reset()
        if outcome == EMPTY:
            sleep(IDLE_POLL_SECONDS)


def start() -> threading.Thread | None:
    """Start the consumer if the switch is on and it has what it needs."""
    global _thread
    if not settings.crm_events_enabled:
        logger.info("crm events off")
        return None
    missing = _missing_configuration()
    if missing:
        logger.error("crm events: CRM_EVENTS_ENABLED is on but %s, so they stay off", missing)
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _thread = threading.Thread(target=run_forever, name="crm-events", daemon=True)
    _thread.start()
    logger.info("crm events on, delivering to %s", settings.crm_events_url)
    return _thread


def reset() -> None:
    """Forget the connection and the alarm. Tests."""
    global _client, _thread, _offline_until
    _client = None
    _thread = None
    _offline_until = 0.0
    _alarm.cleared()
