"""The one file each customer is currently talking about.

In this process, deliberately, and not in the customer's Redis record. That
record is read and rewritten on every single message and lives for seven days;
a PDF put inside it would cross the wire twice a turn for a week, for a file the
conversation is done with after four questions. Same demo-scale bargain
`session_store` makes: a restart forgets it, and the customer sends it again.

What outlives a restart is the line the router wrote in the history where the
file arrived, which is in Redis with everything else. So the worst a restart
costs is a bot that says it can no longer see the file -- not a conversation
that reads as if one was never sent.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.llm import Document

# One file per customer, and a few customers at a time. A demo has a handful of
# people in the room, not a handful of thousands, and the cap is here so that a
# month of strangers each sending a brochure cannot quietly become a gigabyte of
# resident memory. The least recently used one goes.
MAX_DOCUMENTS = 5

_documents: OrderedDict[str, Document] = OrderedDict()


def remember(key: str, document: Document) -> None:
    """File this customer's newest attachment, replacing whatever they sent before.

    One at a time on purpose: "the file we are talking about" is singular in
    every conversation this demo has, and keeping the older ones would mean
    deciding which of them a question is about.
    """
    _documents.pop(key, None)
    _documents[key] = document
    while len(_documents) > MAX_DOCUMENTS:
        _documents.popitem(last=False)


def get(key: str) -> Document | None:
    document = _documents.get(key)
    if document is not None:
        # Asking about a file is what keeps it alive, not having sent it recently.
        _documents.move_to_end(key)
    return document


def forget(key: str) -> None:
    """Drop it. Called when the customer starts the demo over: a new conversation
    that could still quote the last one's PDF is not a new conversation."""
    _documents.pop(key, None)


def clear() -> None:
    _documents.clear()
