"""A CRM agent's reply, sent to WhatsApp at most once however often it is asked.

The inside of `POST /internal/crm/send` (`routers/internal_crm.py` is the door).
The contract is `docs/chatbot-replies.md` section 5 in acuven_crm_demo: the CRM
stores the agent's message first, then asks us to send it, and retries with the
same `request_id` whenever it cannot tell whether the first try went out.

Two promises, and every branch below keeps one of them:

1. However many times one `request_id` arrives, the visitor gets the message at
   most once. A Redis key per request remembers "sending" and then the id Meta
   gave the message; with no Redis to remember it in, nothing is sent at all.
2. The CRM can tell "it was not sent" from "nobody knows". Meta refusing (4xx)
   is the first: the key is freed so a retry really sends, and the CRM drops its
   copy. Meta failing on its own side (5xx), or no answer at all, is the second:
   the key is left to expire, so a retry inside two minutes cannot send twice,
   and the CRM keeps its copy as "not confirmed".

Not the console's path on purpose. `notify._send` swallows a refusal and the
console reports success, which is fine for a person watching the screen and
wrong for a caller that has to decide whether to keep a message (contract
section 13).

Once Meta has the message, contract section 5 step 4, in this order: the key
holds Meta's id, the CRM's `agent_reply` is queued, the takeover starts or is
renewed, and the reply goes into the history and the audit log. Each of the
last two is caught on its own: by then the visitor has the message, and nothing
that fails afterwards may make the answer anything but "sent".
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
import time

from app.console import events
from app.services import audit, crm_events, handover, whatsapp
from app.services.user_store import user_store

logger = logging.getLogger(__name__)

KEY_PREFIX = "chat:crm_send:"
# How long "sending" holds the key. Long enough to outlast one send (Meta gets
# ten seconds) and the CRM's own 30-second limit; short enough that a send that
# died half-way can be retried the same afternoon. Contract section 5.
SENDING_SECONDS = 120
# How long the id is kept. The CRM only retries messages under 24 hours old.
SENT_SECONDS = 48 * 60 * 60
# What of Meta's error title the CRM gets; the CRM stores 300 too.
MAX_TITLE_CHARS = 300

SENDING = {"state": "sending"}

# What the console and the audit log call a reply typed in the CRM. Beside
# `notify.HUMAN_TOOL` ("human.reply"), which is one typed at the console.
CRM_REPLY_TOOL = "crm.reply"

# Same reasoning as `user_store` and `crm_events`: Redis is one hop away, and a
# Redis that is down must cost the CRM a second, not a default timeout.
CONNECT_TIMEOUT_SECONDS = 1.0
OPERATION_TIMEOUT_SECONDS = 1.0


def _default_client(url: str):
    import redis

    return redis.Redis.from_url(
        url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=OPERATION_TIMEOUT_SECONDS,
        decode_responses=True,
    )


# Swapped out by tests, the way `crm_events` does it.
_client_factory = _default_client
_client = None


def _redis():
    global _client
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is empty")
    if _client is None:
        _client = _client_factory(settings.redis_url)
    return _client


def reset() -> None:
    """Forget the connection. Tests."""
    global _client
    _client = None


def _tail(number: str) -> str:
    """Enough of a number to tell two visitors apart in a log, and no more."""
    return f"...{number[-4:]}"


def _known(raw: str | None) -> tuple[int, dict] | None:
    """The answer a key that is already taken decides, or None if it is gone."""
    if raw is None:
        return None
    try:
        sent = json.loads(raw).get("wa_message_id")
    except Exception:
        sent = None
    if sent:
        # Sent before. Not sent again, and no takeover in the answer: whatever
        # happened to the takeover since is not this request's to report, and
        # "now" would be passed off as the moment it changed. Contract section 5.
        return 200, {"result": "duplicate", "wa_message_id": sent, "handover": None}
    return 409, {"result": "in_progress"}


def _refusal(failure: whatsapp.WhatsAppSendError) -> dict:
    """Meta's code and title from a refused send, as far as they can be read."""
    try:
        error = failure.response.json().get("error")
    except Exception:
        error = None
    if not isinstance(error, dict):
        return {"result": "rejected", "error_code": None, "error_title": None}
    code = error.get("code")
    title = error.get("error_user_title") or error.get("title") or error.get("message")
    return {
        "result": "rejected",
        "error_code": code if isinstance(code, int) else None,
        "error_title": str(title)[:MAX_TITLE_CHARS] if title else None,
    }


def _forget(client, key: str, request_id: str) -> None:
    try:
        client.delete(key)
    except Exception:
        # The placeholder expires on its own; until then a retry is a 409.
        logger.exception("crm send %s: could not free the key after a failed send", request_id)


def send(
    *,
    request_id: str,
    phone: str,
    bsuid: str | None,
    text: str,
    agent_id: str,
    agent_name: str,
) -> tuple[int, dict]:
    """Send one agent's reply. Returns the status code and body for the CRM.

    `request_id` arrives canonical (the door parses it as a UUID) and `text`
    trimmed. `bsuid` only helps find the visitor's record.
    """
    key = f"{KEY_PREFIX}{request_id}"

    try:
        client = _redis()
        # Taking the key is the check: NX fails exactly when this request has
        # been seen before, and then what the key holds is the answer. One
        # atomic step, so two copies arriving together cannot both send.
        if not client.set(key, json.dumps(SENDING), nx=True, ex=SENDING_SECONDS):
            # Gone again by the time it is read (the placeholder expired in
            # between): still not ours to send. The next retry will be.
            return _known(client.get(key)) or (409, {"result": "in_progress"})
    except Exception:
        logger.exception("crm send %s: no Redis for the idempotency key, so not sending", request_id)
        return 503, {"result": "unavailable"}

    try:
        payload = whatsapp.build_text_message(phone, text)
    except Exception:
        # Nothing has left this process. Free the key: a retry should send.
        logger.exception("crm send %s: could not build the message", request_id)
        _forget(client, key, request_id)
        return 500, {"result": "error"}

    try:
        response = whatsapp.send_raw(payload)
    except whatsapp.WhatsAppSendError as failure:
        if failure.status_code is not None and 400 <= failure.status_code < 500:
            refused = _refusal(failure)
            logger.warning(
                "crm send %s: Meta refused the reply to %s (HTTP %s, code %s)",
                request_id, _tail(phone), failure.status_code, refused["error_code"],
            )
            _forget(client, key, request_id)
            return 502, refused
        logger.error(
            "crm send %s: Meta failed on its side (HTTP %s); not known whether %s got it",
            request_id, failure.status_code, _tail(phone),
        )
        return 504, {"result": "unknown"}
    except Exception as failure:
        # A timeout, a dropped connection, a refused one: the contract counts
        # all of them as "cannot prove Meta did not take it".
        logger.error(
            "crm send %s: no answer from Meta (%s); not known whether %s got it",
            request_id, type(failure).__name__, _tail(phone),
        )
        return 504, {"result": "unknown"}

    try:
        wa_message_id = response.json()["messages"][0]["id"]
        if not isinstance(wa_message_id, str) or not wa_message_id:
            raise ValueError(wa_message_id)
    except Exception:
        # Meta said yes and did not say to what. Most likely sent; not provably.
        logger.error("crm send %s: Meta accepted the reply but gave no message id", request_id)
        return 504, {"result": "unknown"}

    try:
        client.set(key, json.dumps({"wa_message_id": wa_message_id}), ex=SENT_SECONDS)
    except Exception:
        # It went out, so it is "sent" whatever happens here. The placeholder
        # expires in two minutes, after which a retry would send it again.
        logger.exception("crm send %s: sent as %s but could not record it", request_id, wa_message_id)

    logger.info("crm send %s: sent to %s as %s", request_id, _tail(phone), wa_message_id)

    # First, before anything that reads a record: the event is what fills in
    # the CRM's copy if this answer never reaches it. Its `visitor` is required
    # by the contract and unused by the CRM, so the request's own is enough.
    crm_events.enqueue(
        "agent_reply",
        crm_events.visitor(phone, bsuid, None),
        message={"wa_message_id": wa_message_id, "body": text},
        crm_message_id=request_id,
    )

    try:
        profile = _record_for(phone, bsuid)
    except Exception:
        logger.exception("crm send %s: sent, but could not read the visitor's record", request_id)
        return 200, {"result": "sent", "wa_message_id": wa_message_id, "handover": None}

    taken = _take_over(profile, agent_name, request_id)
    _file(profile, text, wa_message_id, request_id, agent_id, agent_name)
    return 200, {"result": "sent", "wa_message_id": wa_message_id, "handover": taken}


def _record_for(phone: str, bsuid: str | None):
    """The visitor's record: by number, then by BSUID, else a new one by number.

    Filed under one key only (the number where there is one), so a visitor who
    first wrote with their number hidden is under the BSUID -- and should stay
    one record rather than become two.
    """
    return (
        user_store.get(phone)
        or (user_store.get(bsuid) if bsuid else None)
        or user_store.get_or_create(phone)
    )


def _take_over(profile, agent_name: str, request_id: str) -> dict | None:
    """Start or renew the takeover; what changed, for the response. None if it failed.

    `begin` alone would not do: on a conversation already in a person's hands it
    returns without touching anything (asking twice is not a second takeover),
    and a reply has to push the expiry out (contract section 13).
    """
    try:
        if handover.active(profile):
            handover.touch(profile)
        else:
            handover.begin(profile, reason=f"replied from the CRM by {agent_name}")
        # The moment the record carries is the one `handover_changed` was
        # queued with, so the CRM gets one value from both (contract R3).
        return {**handover.crm_state(profile), "occurred_at": crm_events.utc(profile.handover_active_at)}
    except Exception:
        logger.exception("crm send %s: sent, but the takeover did not change", request_id)
        return None


def _file(profile, text: str, wa_message_id: str, request_id: str, agent_id: str, agent_name: str) -> None:
    """Put the reply in the history, the audit log and on the console.

    The same object the takeover was written on, never a fresh read: two copies
    of one record saved one after the other is how a takeover silently vanishes
    (see `handover.begin`).

    The history gets the text alone, as the assistant's -- that is what the
    model reads when the bot is back, and an agent's name in it would be
    something for the model to copy. Who wrote it goes on the audit log's tool
    row and on the console span, where a person reads it.
    """
    started = time.monotonic()
    try:
        profile.add_message("assistant", text)
        # Before the save, so a conversation id minted for a record that had
        # none is kept rather than filed once and forgotten.
        audit.begin_for(profile, audit.WHATSAPP)
        user_store.save(profile)
        who = {"agent_id": agent_id, "agent_name": agent_name, "request_id": request_id}
        audit.record_message("assistant", text, audit.CRM_AGENT)
        audit.record_tool_call(tool=CRM_REPLY_TOOL, tool_use_id=request_id, input=who, output=wa_message_id)
        events.emit(
            type=events.TOOL_START,
            tool=CRM_REPLY_TOOL,
            tool_use_id=request_id,
            input={"to": profile.key_id, "agent": agent_name},
            key_id=profile.key_id,
        )
        events.emit(
            type=events.TOOL_END,
            tool=CRM_REPLY_TOOL,
            tool_use_id=request_id,
            output=text,
            duration_ms=int((time.monotonic() - started) * 1000),
            status="ok",
            key_id=profile.key_id,
        )
    except Exception:
        logger.exception("crm send %s: sent, but could not file it in the history or the audit log", request_id)
    finally:
        audit.close()
