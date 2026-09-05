from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

from app.config import settings

MAX_HISTORY_TURNS = 20
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class SessionStore:
    """Per-message and per-day bookkeeping for one running process.

    What a customer said and which demo they are in moved to `user_store` --
    task 32 for WhatsApp, task 33 for the web chat -- so both channels remember
    the same person for seven days instead of until the next restart. What is
    left here is the state that is genuinely about this process's lifetime: which
    message ids have already been handled, and how many messages a number has
    sent today.

    Demo-scale only: no persistence, no eviction. Must run as a single process
    (see docker-compose.yml) since neither counter is shared across workers.
    """

    def __init__(self, daily_msg_limit: int) -> None:
        self._daily_msg_limit = daily_msg_limit
        self._daily_counts: dict[tuple[str, date], int] = {}
        self._seen_message_ids: dict[str, float] = {}

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
