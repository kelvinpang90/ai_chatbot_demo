from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import NamedTuple

from app.config import settings
from app.services import whatsapp

logger = logging.getLogger(__name__)


class Attachment(NamedTuple):
    """A file already uploaded to Meta, waiting for the reply it travels with."""

    media_id: str
    filename: str
    caption: str

    def build(self, to: str) -> dict:
        return whatsapp.build_document_message(
            to, self.media_id, filename=self.filename, caption=self.caption
        )


class Choices(NamedTuple):
    """A set of options the customer taps instead of typing them back.

    Rows come from `whatsapp.list_row`, so they are already inside the channel's
    lengths by the time they get here. The tap arrives as an inbound interactive
    message carrying the row's id, which is what the sender of the list uses to
    tell one option from another -- see `_resolve_product_choice`.
    """

    body: str
    button: str
    section_title: str
    rows: list[dict]

    def build(self, to: str) -> dict:
        return whatsapp.build_interactive_list(
            to,
            body_text=self.body,
            button_text=self.button,
            sections=[{"title": self.section_title, "rows": self.rows}],
        )


class FlowForm(NamedTuple):
    """A native form for the customer to fill in without leaving WhatsApp.

    The third thing a tool can leave here, and the reason the note below says
    this module has no branch per message type: it knows how to address itself,
    so nothing in `add` or `drain` learned a new word for it.

    What comes back is not another item in here -- a filled form arrives as an
    ordinary inbound message on the webhook, hours later if the customer puts
    their phone down. See `_handle_flow_reply` in the webhook router.
    """

    body: str
    flow_id: str
    flow_token: str
    cta: str
    screen: str
    data: dict

    def build(self, to: str) -> dict:
        return whatsapp.build_flow_message(
            to,
            body_text=self.body,
            flow_id=self.flow_id,
            flow_token=self.flow_token,
            cta=self.cta,
            screen=self.screen,
            data=self.data,
            mode=settings.whatsapp_flow_mode,
        )


# Anything a tool can leave behind for the reply to carry. Each knows how to
# address itself, so this module never grows a branch per message type: the
# outbox's job is when things go out, not what they are.
Outgoing = Attachment | Choices | FlowForm


# Per conversation, not per process: replies run in FastAPI's sync threadpool and
# two customers can be mid-answer at the same moment. The default is None rather
# than an empty list, and that distinction is load-bearing -- see `available`.
_pending: ContextVar[list[Outgoing] | None] = ContextVar("outbox_pending", default=None)


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


def add(item: Outgoing) -> bool:
    """Queue something to go out with the reply. False if nothing will send it."""
    pending = _pending.get()
    if pending is None:
        logger.warning("no outbox open, dropping %s", type(item).__name__)
        return False
    pending.append(item)
    return True


def drain(to: str) -> list[dict]:
    """The queued items as messages for `to`, emptying the queue."""
    pending = _pending.get()
    if not pending:
        return []
    _pending.set([])
    return [item.build(to) for item in pending]
