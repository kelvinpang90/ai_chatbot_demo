from __future__ import annotations

import itertools
import threading
import time
from collections import deque

from pydantic import BaseModel

# Enough to hold a whole demo's worth of tool calls without ever growing.
MAX_EVENTS = 200

TOOL_START = "tool_start"
TOOL_END = "tool_end"
# A reply that never reached the customer. On the director's screen this is the
# one event worth interrupting a demo for: everything else on the console is
# something that worked, and a silent failure looks exactly like a pause.
SEND_FAILED = "send_failed"


class ConsoleEvent(BaseModel):
    seq: int
    at: float
    type: str
    tool: str
    tool_use_id: str
    input: dict | None = None
    output: str | None = None
    duration_ms: int | None = None
    status: str | None = None  # "ok" | "error", set on TOOL_END


# The chat request runs in FastAPI's sync threadpool while the SSE endpoint runs on
# the event loop, so the buffer is shared across threads and takes a lock. Readers
# poll it by sequence number rather than being pushed to: one source of truth, no
# per-subscriber queue to leak when a browser tab closes mid-demo.
_lock = threading.Lock()
_events: deque[ConsoleEvent] = deque(maxlen=MAX_EVENTS)
_counter = itertools.count(1)


def emit(
    *,
    type: str,
    tool: str,
    tool_use_id: str,
    input: dict | None = None,
    output: str | None = None,
    duration_ms: int | None = None,
    status: str | None = None,
) -> ConsoleEvent:
    with _lock:
        event = ConsoleEvent(
            seq=next(_counter),
            at=time.time(),
            type=type,
            tool=tool,
            tool_use_id=tool_use_id,
            input=input,
            output=output,
            duration_ms=duration_ms,
            status=status,
        )
        _events.append(event)
    return event


def since(seq: int) -> list[ConsoleEvent]:
    """Everything newer than `seq`, oldest first."""
    with _lock:
        return [event for event in _events if event.seq > seq]


def latest_seq() -> int:
    with _lock:
        return _events[-1].seq if _events else 0


def clear() -> None:
    with _lock:
        _events.clear()
