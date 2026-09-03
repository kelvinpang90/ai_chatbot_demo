from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import NamedTuple

from app.services import whatsapp

logger = logging.getLogger(__name__)


class Attachment(NamedTuple):
    """A file already uploaded to Meta, waiting for the reply it travels with."""

    media_id: str
    filename: str
    caption: str


# Per conversation, not per process: replies run in FastAPI's sync threadpool and
# two customers can be mid-answer at the same moment. The default is None rather
# than an empty list, and that distinction is load-bearing -- see `available`.
_pending: ContextVar[list[Attachment] | None] = ContextVar("outbox_pending", default=None)


def begin() -> None:
    """Open an outbox for one inbound message. Call before the model runs."""
    _pending.set([])


def close() -> None:
    """Drop the outbox. For tests.

    Production never needs it: every inbound message is handled in its own
    context -- a background task and an event-loop task each copy the caller's --
    so `begin` cannot reach the next one. A test suite shares one context, and a
    file left open there would be sent to whoever the next test invents.
    """
    _pending.set(None)


def available() -> bool:
    """Whether anything will actually be sent if a tool leaves a file here.

    A tool has to be able to tell the model the truth about what the customer
    will receive, and only the WhatsApp path opens an outbox. The web chat in
    `routers/chat.py` has no channel to put a document on, so a tool that
    attaches one there must say the file was not delivered rather than let the
    bot promise a PDF that never arrives.
    """
    return _pending.get() is not None


def add(attachment: Attachment) -> bool:
    """Queue a file to go out with the reply. False if nothing will send it."""
    pending = _pending.get()
    if pending is None:
        logger.warning("no outbox open, dropping attachment %s", attachment.filename)
        return False
    pending.append(attachment)
    return True


def drain(to: str) -> list[dict]:
    """The queued files as messages for `to`, emptying the queue."""
    pending = _pending.get()
    if not pending:
        return []
    _pending.set([])
    return [
        whatsapp.build_document_message(
            to, item.media_id, filename=item.filename, caption=item.caption
        )
        for item in pending
    ]
