from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections import deque

from pydantic import BaseModel

# Enough to hold a whole demo's worth of tool calls without ever growing.
MAX_EVENTS = 200

# Which run of this process a sequence number belongs to. Sequence numbers start
# again at 1 when the service restarts, so a console that remembers what it has
# already seen -- which it must, or a reconnect replays the buffer into duplicate
# rows -- would take every event after a redeploy for one it had seen before and
# quietly show nothing. Handing the id out lets it tell the two apart.
BOOT_ID = uuid.uuid4().hex

TOOL_START = "tool_start"
TOOL_END = "tool_end"
# A reply that never reached the customer. On the director's screen this is the
# one event worth interrupting a demo for: everything else on the console is
# something that worked, and a silent failure looks exactly like a pause.
SEND_FAILED = "send_failed"
# What one call to Claude cost. Emitted per API response, not per reply: a turn
# that runs a tool loop makes several, and only counting the last one would put a
# figure on the screen that is a fraction of what was actually spent.
USAGE = "usage"


class ConsoleEvent(BaseModel):
    seq: int
    at: float
    type: str
    # Both empty on a USAGE event, which belongs to the turn rather than to any
    # one tool.
    tool: str = ""
    tool_use_id: str = ""
    input: dict | None = None
    output: str | None = None
    duration_ms: int | None = None
    status: str | None = None  # "ok" | "error", set on TOOL_END
    model: str | None = None  # USAGE only
    tokens: dict | None = None  # USAGE only: input / output / cache_write / cache_read
    cost_myr: float | None = None  # USAGE only


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
    tool: str = "",
    tool_use_id: str = "",
    input: dict | None = None,
    output: str | None = None,
    duration_ms: int | None = None,
    status: str | None = None,
    model: str | None = None,
    tokens: dict | None = None,
    cost_myr: float | None = None,
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
            model=model,
            tokens=tokens,
            cost_myr=cost_myr,
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
