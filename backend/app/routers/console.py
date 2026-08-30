from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

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


@router.get("/stream")
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
