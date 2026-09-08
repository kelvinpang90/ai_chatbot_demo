from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from app.config import settings

if TYPE_CHECKING:
    from app.services.user_store import UserProfile

logger = logging.getLogger(__name__)

WHATSAPP = "whatsapp"
WEB = "web"

# How a customer's words reached us. Worth a column of its own because "they
# spoke it" and "they tapped it off a list" are two of the things a demo is
# meant to prove, and by the time a message is recorded all three look alike --
# a voice note is transcribed into plain text before anything downstream sees
# it, and a list tap is resolved into the sentence it stands for.
TEXT = "text"
VOICE = "voice"
INTERACTIVE = "interactive"

# The console's ring buffer holds 200 events and forgets them on restart; this is
# the copy that outlives the demo. Long values are still capped, because one
# runaway tool output should cost its own row's tail, not the row.
MAX_CONTENT_CHARS = 64_000
MAX_TOOL_OUTPUT_CHARS = 64_000

# Same posture as the user store: once writing has failed, stop paying the
# timeout on every message and try again in half a minute.
RETRY_AFTER_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 2.0

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        conversation_id CHAR(36) NOT NULL,
        key_id VARCHAR(64) NOT NULL,
        channel VARCHAR(16) NOT NULL,
        bot_id VARCHAR(32) NOT NULL,
        role VARCHAR(16) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        source VARCHAR(16) NOT NULL DEFAULT 'text',
        created_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_key (key_id, id),
        KEY idx_conversation (conversation_id, id),
        KEY idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        conversation_id CHAR(36) NOT NULL,
        key_id VARCHAR(64) NOT NULL,
        message_id BIGINT UNSIGNED NULL,
        tool VARCHAR(64) NOT NULL,
        tool_use_id VARCHAR(64) NOT NULL,
        input JSON NULL,
        output MEDIUMTEXT NULL,
        duration_ms INT NULL,
        status VARCHAR(16) NOT NULL,
        created_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_conversation (conversation_id, id),
        KEY idx_message (message_id),
        KEY idx_tool (tool, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS model_usage (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        conversation_id CHAR(36) NOT NULL,
        key_id VARCHAR(64) NOT NULL,
        message_id BIGINT UNSIGNED NULL,
        bot_id VARCHAR(32) NOT NULL,
        model VARCHAR(64) NOT NULL,
        input_tokens INT NOT NULL DEFAULT 0,
        output_tokens INT NOT NULL DEFAULT 0,
        cache_write_tokens INT NOT NULL DEFAULT 0,
        cache_read_tokens INT NOT NULL DEFAULT 0,
        api_turns INT NOT NULL DEFAULT 1,
        created_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_conversation (conversation_id, id),
        KEY idx_message (message_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)


def new_conversation_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Turn:
    """Who this exchange belongs to, for as long as it is being handled.

    A tool call knows its own name and arguments but not whose conversation it is
    in -- the console has emitted them without an owner since task 3, which is
    exactly why its feed cannot be filed. Carrying the owner in a ContextVar
    keeps `events.emit` and the tool functions untouched: production handles each
    inbound message in its own context (a threadpool call or an asyncio task,
    both of which copy one), so two customers writing at once cannot see each
    other's turn.
    """

    conversation_id: str
    key_id: str
    channel: str
    bot_id: str
    # The row a tool call or a usage line hangs off: the customer message being
    # answered. Set when that message is written, so anything recorded before
    # then is unattached rather than attached to the wrong turn.
    message_id: int | None = None


_turn: ContextVar[Turn | None] = ContextVar("audit_turn", default=None)


def begin(*, conversation_id: str, key_id: str, channel: str, bot_id: str) -> None:
    _turn.set(
        Turn(conversation_id=conversation_id, key_id=key_id, channel=channel, bot_id=bot_id)
    )


def begin_for(profile: "UserProfile", channel: str) -> None:
    """Open a turn for this customer, minting a conversation id if they have none.

    Both channels come through here so that "when does a customer get a
    conversation id" is answered once. It has to cope with a profile that
    predates the audit log -- those are live in Redis for seven days at a time --
    which is why the id is filled in on use rather than only at creation.

    The caller still has to `user_store.save(profile)` for a minted id to
    outlive the request; a turn that is never saved simply files its rows under
    an id nothing else refers to, which is a worse transcript, not a wrong one.
    """
    if not profile.conversation_id:
        profile.conversation_id = new_conversation_id()
    begin(
        conversation_id=profile.conversation_id,
        key_id=profile.key_id,
        channel=channel,
        bot_id=profile.bot_id or "",
    )


def close() -> None:
    _turn.set(None)


def current() -> Turn | None:
    return _turn.get()


def _dsn(url: str) -> dict | None:
    """Connection kwargs from a `mysql://user:pass@host:port/db` URL, or None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("mysql", "mysql+pymysql") or not parsed.hostname:
        logger.warning("MYSQL_URL is not a mysql:// url; the audit log is off")
        return None
    database = (parsed.path or "").lstrip("/")
    if not database:
        logger.warning("MYSQL_URL names no database; the audit log is off")
        return None
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        # A generated password is very likely to contain reserved characters, so
        # the URL carries it percent-encoded and it is decoded back here.
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    }


class AuditStore:
    """Every message, tool call and token bill, on disk, for as long as we keep it.

    Deliberately unlike `user_store` in one respect: there is no in-memory
    fallback. A profile held in memory still does its job -- the bot remembers
    the customer until the container restarts -- but an audit row held in memory
    is a record that will be lost while looking like it was kept. If MySQL is
    down the row is dropped and the log says so.

    What they share is the rule that matters: nothing here may take the demo
    down. Every call is wrapped, every failure opens a circuit for half a minute,
    and the caller is never told, because there is nothing a caller could do
    about it in the middle of answering a customer.

    One connection behind one lock. FastAPI runs these sync paths on its
    threadpool and a PyMySQL connection is not thread-safe, so the choice is a
    pool, a connection per thread, or a lock. At demo volume -- the busiest
    moment this has to survive is three people in a room writing at once, each
    costing a few sub-millisecond inserts -- the lock is the one with no moving
    parts.
    """

    def __init__(self, url: str, connect=None) -> None:
        self._url = url
        self._connect = connect or _default_connect
        self._lock = threading.Lock()
        self._conn = None
        self._offline_until = 0.0
        self._schema_ready = False

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def record_message(
        self,
        *,
        turn: Turn,
        role: str,
        content: str,
        source: str = TEXT,
        at: float | None = None,
    ) -> int | None:
        """Write one side of an exchange; returns its row id, or None if unwritten."""
        return self._write(
            "INSERT INTO chat_messages"
            " (conversation_id, key_id, channel, bot_id, role, content, source, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                turn.conversation_id,
                turn.key_id,
                turn.channel,
                turn.bot_id,
                role,
                content[:MAX_CONTENT_CHARS],
                source,
                _timestamp(at),
            ),
        )

    def record_tool_call(
        self,
        *,
        turn: Turn,
        tool: str,
        tool_use_id: str,
        input: dict | None,
        output: str | None,
        duration_ms: int | None,
        status: str,
        at: float | None = None,
    ) -> None:
        self._write(
            "INSERT INTO tool_calls"
            " (conversation_id, key_id, message_id, tool, tool_use_id, input, output,"
            "  duration_ms, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                turn.conversation_id,
                turn.key_id,
                turn.message_id,
                tool[:64],
                tool_use_id[:64],
                _json_or_none(input),
                None if output is None else output[:MAX_TOOL_OUTPUT_CHARS],
                duration_ms,
                status,
                _timestamp(at),
            ),
        )

    def record_usage(
        self,
        *,
        turn: Turn,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int,
        cache_read_tokens: int,
        api_turns: int,
        at: float | None = None,
    ) -> None:
        self._write(
            "INSERT INTO model_usage"
            " (conversation_id, key_id, message_id, bot_id, model, input_tokens,"
            "  output_tokens, cache_write_tokens, cache_read_tokens, api_turns, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                turn.conversation_id,
                turn.key_id,
                turn.message_id,
                turn.bot_id,
                model[:64],
                input_tokens,
                output_tokens,
                cache_write_tokens,
                cache_read_tokens,
                api_turns,
                _timestamp(at),
            ),
        )

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Read rows back. Returns [] when the log is off or unreachable."""
        import pymysql.cursors

        with self._lock:
            conn = self._connection()
            if conn is None:
                return []
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
            except Exception:
                self._go_offline("read failed")
                return []

    def reset(self) -> None:
        """Drop the connection and re-close the circuit. Tests."""
        with self._lock:
            self._conn = None
            self._offline_until = 0.0
            self._schema_ready = False

    def _write(self, sql: str, params: tuple) -> int | None:
        with self._lock:
            conn = self._connection()
            if conn is None:
                return None
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.lastrowid
            except Exception:
                self._go_offline("write failed")
                return None

    def _connection(self):
        """A usable connection, or None meaning "drop this row". Holds the lock."""
        if not self._url or time.time() < self._offline_until:
            return None
        if self._conn is None:
            dsn = _dsn(self._url)
            if dsn is None:
                # A malformed URL will not fix itself in thirty seconds, so this
                # one stays down until the process restarts with a good one.
                self._offline_until = float("inf")
                return None
            try:
                self._conn = self._connect(dsn)
            except Exception:
                self._go_offline("could not connect")
                return None
        try:
            # Cheap, and the alternative is losing the first row after every idle
            # period longer than MySQL's wait_timeout -- which, between two
            # demos, is every one of them.
            self._conn.ping(reconnect=True)
        except Exception:
            self._go_offline("ping failed")
            return None
        if not self._schema_ready:
            try:
                with self._conn.cursor() as cursor:
                    for statement in SCHEMA:
                        cursor.execute(statement)
                self._schema_ready = True
            except Exception:
                self._go_offline("could not create the audit tables")
                return None
        return self._conn

    def _go_offline(self, reason: str) -> None:
        self._conn = None
        self._schema_ready = False
        self._offline_until = time.time() + RETRY_AFTER_SECONDS
        logger.warning("audit log unavailable, dropping rows: %s", reason, exc_info=True)


def _default_connect(dsn: dict):
    # Imported here, not at module scope, so a deployment without the package --
    # or without a MySQL at all -- runs with the audit log off instead of failing
    # to boot.
    import pymysql

    return pymysql.connect(**dsn)


def _timestamp(at: float | None) -> str:
    seconds = time.time() if at is None else at
    whole = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(seconds))
    return f"{whole}.{int(seconds % 1 * 1000):03d}"


def _json_or_none(value: dict | None) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        # A tool argument that will not serialise should cost its own column, not
        # the row that says the tool was called at all.
        logger.warning("could not serialise tool input for the audit log", exc_info=True)
        return None


# An empty MYSQL_URL means the audit log is off, which is what the test suite and
# anyone running this without the shared infrastructure get.
audit_store = AuditStore(settings.mysql_url)


def record_message(role: str, content: str, source: str = TEXT) -> None:
    """File one message against the turn in flight. Does nothing outside one."""
    turn = _turn.get()
    if turn is None or not audit_store.enabled:
        return
    row_id = audit_store.record_message(turn=turn, role=role, content=content, source=source)
    if row_id is not None:
        turn.message_id = row_id


def record_tool_call(
    *,
    tool: str,
    tool_use_id: str,
    input: dict | None = None,
    output: str | None = None,
    duration_ms: int | None = None,
    status: str = "ok",
) -> None:
    turn = _turn.get()
    if turn is None or not audit_store.enabled:
        return
    audit_store.record_tool_call(
        turn=turn,
        tool=tool,
        tool_use_id=tool_use_id,
        input=input,
        output=output,
        duration_ms=duration_ms,
        status=status,
    )


def record_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_read_tokens: int,
    api_turns: int,
) -> None:
    turn = _turn.get()
    if turn is None or not audit_store.enabled:
        return
    audit_store.record_usage(
        turn=turn,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_read_tokens=cache_read_tokens,
        api_turns=api_turns,
    )
