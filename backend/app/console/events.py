from __future__ import annotations

import itertools
import threading
import time
import uuid
from collections import deque
from contextvars import ContextVar

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
# The control-arm switch being thrown (task 12.2). Not a tool call, but it belongs
# in the same feed and at the same point in time: without it, the stretch of the
# demo where the bot answers from nothing looks identical to a stretch where
# nothing happened to be asked. `status` carries "on" or "off".
TOOLS_SWITCHED = "tools_switched"


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
    # "ok" | "error" on TOOL_END; "on" | "off" on TOOLS_SWITCHED.
    status: str | None = None
    model: str | None = None  # USAGE only
    tokens: dict | None = None  # USAGE only: input / output / cache_write / cache_read
    cost_myr: float | None = None  # USAGE only
    # Whose event this is: the customer's filing key (a phone number, or a BSUID
    # for someone behind a username). Blank for what belongs to nobody -- the
    # tools switch, a message nobody could be identified from. What a page that
    # shows one customer's console filters on (task 37.6).
    key_id: str = ""


# The chat request runs in FastAPI's sync threadpool while the SSE endpoint runs on
# the event loop, so the buffer is shared across threads and takes a lock. Readers
# poll it by sequence number rather than being pushed to: one source of truth, no
# per-subscriber queue to leak when a browser tab closes mid-demo.
_lock = threading.Lock()
_events: deque[ConsoleEvent] = deque(maxlen=MAX_EVENTS)
_counter = itertools.count(1)

# The customer whose inbound message is being handled, stamped on everything
# emitted while it is. Set once, where the sender is first known, rather than
# threaded through every function that might emit: a voice note's transcription
# span, a photo download, the model's tool calls and the send that follows all
# happen under it, and the first of those fire before any audit turn opens -- so
# the turn could not have supplied the key.
#
# A ContextVar for the outbox's reason: each inbound message is handled in its own
# context, so one customer's key cannot reach another's events. What runs on a
# thread of its own -- a timed push -- inherits nothing and names its customer
# at the call instead.
_customer: ContextVar[str] = ContextVar("console_event_customer", default="")


def set_customer(key_id: str) -> None:
    """File what this context emits from here on under this customer."""
    _customer.set(key_id or "")


def clear_customer() -> None:
    """Stop filing under anybody. For tests; production never reuses a context."""
    _customer.set("")


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
    # Named outright by a caller that knows better than the context does -- a
    # handover started from the console, a push on a timer thread. Otherwise the
    # customer being served.
    key_id: str | None = None,
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
            key_id=_customer.get() if key_id is None else key_id,
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
