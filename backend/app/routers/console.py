from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.console import events
from app.models import (
    ConversationDetail,
    ConversationSummary,
    HistoryPage,
    ToolCallRecord,
    TranscriptMessage,
)
from app.services.audit import audit_store
from app.services.user_store import identity, user_store

router = APIRouter(prefix="/console")

# A quarter second is invisible to someone watching a screen and costs one cheap
# list scan per subscriber.
POLL_INTERVAL_SECONDS = 0.25
# Proxies drop a stream that says nothing for long enough; say something.
KEEPALIVE_SECONDS = 15.0

# A page of conversations. The whole point of the list is to find one, so it is
# ordered by recency and paged rather than counted.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def require_console_token(
    request: Request,
    # EventSource cannot set request headers, so the live stream has no way to
    # send one and the token has to be able to travel in the query string. That
    # puts it in proxy logs, which is the price of the feature; everything under
    # here is read-only and the token is rotatable.
    token: str | None = Query(default=None),
) -> None:
    """Let the caller through only with the configured token.

    Unset means closed. `/console/stream` used to be protected by nothing but the
    fact that the frontend nginx did not proxy `/console/`, and both task 12 and
    task 37.1 needed that proxy rule -- so the accident had to become a gate.

    A token in a query string is weaker than one in a header: it lands in browser
    history and in the proxy's access log. It is still the right trade, because
    EventSource cannot set headers and the alternative is a live feed of orders
    and customer names open to anyone with the link. The header is accepted too,
    for the callers that can send one.
    """
    expected = settings.console_token
    if not expected:
        raise HTTPException(status_code=503, detail="The console is not configured")
    supplied = request.headers.get("X-Console-Token") or token or ""
    # Constant time, so a wrong token cannot be improved one character at a time.
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Bad or missing console token")


def _format(event: events.ConsoleEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(replay: bool) -> AsyncIterator[str]:
    cursor = 0 if replay else events.latest_seq()
    silent_for = 0.0

    # Say something before there is anything to say, for two reasons. It flushes
    # the response headers: measured on the deployed site, without a first byte
    # the page sat on "connecting..." until the first keepalive, because a proxy
    # between here and the browser holds the response until something flushes it.
    # And it names this run of the process, so a console can tell a replayed
    # event from a brand-new one whose sequence number happens to be low.
    yield f'event: hello\ndata: {{"boot_id": "{events.BOOT_ID}"}}\n\n'

    while True:
        batch = events.since(cursor)
        if batch:
            cursor = batch[-1].seq
            silent_for = 0.0
            for event in batch:
                yield _format(event)
        else:
            silent_for += POLL_INTERVAL_SECONDS
            if silent_for >= KEEPALIVE_SECONDS:
                silent_for = 0.0
                yield ": keepalive\n\n"

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@router.get("/stream", dependencies=[Depends(require_console_token)])
async def stream(replay: bool = False) -> StreamingResponse:
    """Live tool-call feed for the director's console.

    Subscribing shows what happens from now on; `?replay=true` replays the buffer
    first, for a screen that connects after the conversation has already started.
    """
    return StreamingResponse(
        _event_stream(replay),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx must not sit on the chunks
        },
    )


def _at(value) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds") if value else ""


def _known_name(key_id: str) -> str | None:
    """The name this customer gave us, if their profile has not expired yet.

    A transcript from two months ago will only have a number, which is the honest
    answer: the name is in the profile, and profiles last seven days. Worth the
    lookup anyway -- a list of names is searchable by a human in a way a list of
    phone numbers is not.
    """
    try:
        profile = user_store.get(key_id)
    except ValueError:
        return None
    return profile.display_name if profile else None


def _loads(value) -> dict | None:
    """A JSON column comes back as text on some drivers and parsed on others."""
    if value is None or isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


@router.get(
    "/history", response_model=HistoryPage, dependencies=[Depends(require_console_token)]
)
def list_conversations(
    key: str | None = None,
    bot_id: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> HistoryPage:
    """Every demo that has been run, most recent first.

    `key` is a phone number in any of the ways one gets written -- it goes
    through the same normalisation the profiles are filed under, so the number a
    salesperson has in their phone finds the conversation the customer had.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    where, params = [], []
    if key:
        try:
            where.append("m.key_id = %s")
            params.append(identity(key))
        except ValueError:
            # Not a number anything could be filed under, so nothing matches it.
            return HistoryPage(conversations=[], limit=limit, offset=offset)
    if bot_id:
        where.append("m.bot_id = %s")
        params.append(bot_id)
    clause = f" WHERE {' AND '.join(where)}" if where else ""

    rows = audit_store.query(
        "SELECT m.conversation_id, MAX(m.key_id) AS key_id, MAX(m.channel) AS channel,"
        " MAX(m.bot_id) AS bot_id, COUNT(*) AS messages,"
        " MIN(m.created_at) AS started_at, MAX(m.created_at) AS last_at"
        f" FROM chat_messages m{clause}"
        " GROUP BY m.conversation_id ORDER BY last_at DESC LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    if not rows:
        return HistoryPage(conversations=[], limit=limit, offset=offset)

    # Counted separately rather than joined in: a join against two one-to-many
    # tables multiplies the rows out, and COUNT(*) on the product is wrong in a
    # way that looks plausible.
    ids = [row["conversation_id"] for row in rows]
    placeholders = ", ".join(["%s"] * len(ids))
    tools = {
        row["conversation_id"]: row["n"]
        for row in audit_store.query(
            f"SELECT conversation_id, COUNT(*) AS n FROM tool_calls"
            f" WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id",
            tuple(ids),
        )
    }
    usage = {
        row["conversation_id"]: row
        for row in audit_store.query(
            "SELECT conversation_id, COALESCE(SUM(input_tokens), 0) AS input_tokens,"
            " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
            " COALESCE(SUM(cost_myr), 0) AS cost_myr,"
            # One row per API call, so the number of round trips is the row count.
            " COUNT(*) AS api_turns FROM model_usage"
            f" WHERE conversation_id IN ({placeholders}) GROUP BY conversation_id",
            tuple(ids),
        )
    }

    return HistoryPage(
        limit=limit,
        offset=offset,
        conversations=[
            ConversationSummary(
                conversation_id=row["conversation_id"],
                key_id=row["key_id"],
                display_name=_known_name(row["key_id"]),
                channel=row["channel"],
                bot_id=row["bot_id"],
                messages=row["messages"],
                tool_calls=tools.get(row["conversation_id"], 0),
                input_tokens=int(usage.get(row["conversation_id"], {}).get("input_tokens", 0)),
                output_tokens=int(usage.get(row["conversation_id"], {}).get("output_tokens", 0)),
                api_turns=int(usage.get(row["conversation_id"], {}).get("api_turns", 0)),
                cost_myr=float(usage.get(row["conversation_id"], {}).get("cost_myr", 0)),
                started_at=_at(row["started_at"]),
                last_at=_at(row["last_at"]),
            )
            for row in rows
        ],
    )


@router.get(
    "/history/{conversation_id}",
    response_model=ConversationDetail,
    dependencies=[Depends(require_console_token)],
)
def read_conversation(conversation_id: str) -> ConversationDetail:
    """One conversation in full: what was said, and what was called in between."""
    messages = audit_store.query(
        "SELECT id, key_id, channel, bot_id, role, content, source, created_at"
        " FROM chat_messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )
    if not messages:
        raise HTTPException(status_code=404, detail="No such conversation")

    calls = audit_store.query(
        "SELECT message_id, tool, tool_use_id, input, output, duration_ms, status, created_at"
        " FROM tool_calls WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    )
    by_message: dict[int | None, list[ToolCallRecord]] = {}
    for call in calls:
        by_message.setdefault(call["message_id"], []).append(
            ToolCallRecord(
                tool=call["tool"],
                tool_use_id=call["tool_use_id"],
                input=_loads(call["input"]),
                output=call["output"],
                duration_ms=call["duration_ms"],
                status=call["status"],
                at=_at(call["created_at"]),
            )
        )

    totals = audit_store.query(
        "SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,"
        " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
        " COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,"
        " COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,"
        " COALESCE(SUM(cost_myr), 0) AS cost_myr,"
        " COUNT(*) AS api_turns"
        " FROM model_usage WHERE conversation_id = %s",
        (conversation_id,),
    )
    total = totals[0] if totals else {}

    return ConversationDetail(
        conversation_id=conversation_id,
        key_id=messages[0]["key_id"],
        display_name=_known_name(messages[0]["key_id"]),
        channel=messages[0]["channel"],
        bot_id=messages[0]["bot_id"],
        messages=[
            TranscriptMessage(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                source=row["source"],
                at=_at(row["created_at"]),
                tool_calls=by_message.get(row["id"], []),
            )
            for row in messages
        ],
        input_tokens=int(total.get("input_tokens", 0)),
        output_tokens=int(total.get("output_tokens", 0)),
        cache_write_tokens=int(total.get("cache_write_tokens", 0)),
        cache_read_tokens=int(total.get("cache_read_tokens", 0)),
        api_turns=int(total.get("api_turns", 0)),
        cost_myr=float(total.get("cost_myr", 0)),
    )
