from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import secrets

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.console import events

router = APIRouter(prefix="/console")

# A quarter second is invisible to someone watching a screen and costs one cheap
# list scan per subscriber.
POLL_INTERVAL_SECONDS = 0.25
# Proxies drop a stream that says nothing for long enough; say something.
KEEPALIVE_SECONDS = 15.0


def _format(event: events.ConsoleEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(replay: bool) -> AsyncIterator[str]:
    cursor = 0 if replay else events.latest_seq()
    silent_for = 0.0

    # Say something before saying anything, so the response headers leave the
    # building at once. Measured on the deployed site: without this the page sat
    # on "connecting..." for as long as it took the first keepalive to arrive,
    # because a proxy between here and the browser holds the response until
    # something flushes it. Which proxy does not matter -- one byte now is the
    # fix at either end of the chain.
    yield ": connected\n\n"

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


def _check_token(token: str | None) -> None:
    """The gate on the feed. Query parameter, because EventSource sends no headers.

    A token in a URL is weaker than a header -- it lands in browser history and in
    the proxy's access log -- and it is still the right trade here: the alternative
    is a stream of live orders and customer names open to anyone with the link.
    """
    if not settings.console_token:
        raise HTTPException(status_code=503, detail="CONSOLE_TOKEN is not configured")
    if not token or not secrets.compare_digest(token, settings.console_token):
        raise HTTPException(status_code=401, detail="Bad console token")


@router.get("/stream")
async def stream(token: str | None = None, replay: bool = False) -> StreamingResponse:
    """Live tool-call feed for the director's console.

    Subscribing shows what happens from now on; `?replay=true` replays the buffer
    first, for a screen that connects after the conversation has already started.
    """
    _check_token(token)
    return StreamingResponse(
        _event_stream(replay),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx must not sit on the chunks
        },
    )
