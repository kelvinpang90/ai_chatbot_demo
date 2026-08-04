from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from app.config import settings

MAX_HISTORY_TURNS = 20
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class Session:
    session_key: str
    bot_id: str | None = None
    identity_id: str | None = None
    history: list[Message] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        self.history.append(Message(role=role, content=content))
        if len(self.history) > MAX_HISTORY_MESSAGES:
            del self.history[: len(self.history) - MAX_HISTORY_MESSAGES]

    def reset(self) -> None:
        self.bot_id = None
        self.identity_id = None
        self.history.clear()


class SessionStore:
    """In-memory session store, keyed by web session_id or WhatsApp phone number.

    Demo-scale only: no persistence, no eviction. Must run as a single process
    (see docker-compose.yml) since state isn't shared across workers.
    """

    def __init__(self, daily_msg_limit: int) -> None:
        self._sessions: dict[str, Session] = {}
        self._daily_msg_limit = daily_msg_limit
        self._daily_counts: dict[tuple[str, date], int] = {}
        self._seen_message_ids: dict[str, float] = {}

    def get_or_create(self, session_key: str) -> Session:
        return self._sessions.setdefault(session_key, Session(session_key=session_key))

    def get(self, session_key: str) -> Session | None:
        return self._sessions.get(session_key)

    def reset(self, session_key: str) -> None:
        session = self._sessions.get(session_key)
        if session:
            session.reset()

    def delete(self, session_key: str) -> None:
        self._sessions.pop(session_key, None)

    def check_and_increment_daily_count(self, phone_number: str) -> bool:
        """Returns True if this message is within today's limit for the number, False if it should be blocked."""
        key = (phone_number, date.today())
        count = self._daily_counts.get(key, 0)
        if count >= self._daily_msg_limit:
            return False
        self._daily_counts[key] = count + 1
        return True

    def is_duplicate_message(self, message_id: str) -> bool:
        """Checks and marks a WhatsApp message id as seen in one call. True means skip it (already processed)."""
        if message_id in self._seen_message_ids:
            return True
        self._seen_message_ids[message_id] = time.time()
        return False


session_store = SessionStore(daily_msg_limit=settings.whatsapp_daily_msg_limit)
