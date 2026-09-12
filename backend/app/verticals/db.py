"""The one MySQL connection the verticals share.

Built on the same bones as `services/audit.py` -- PyMySQL, hand-written SQL, one
connection behind one lock, `CREATE TABLE IF NOT EXISTS` run lazily on first use,
and a circuit that stays open for half a minute after a failure rather than
paying the connect timeout on every request.

**It differs from the audit log in the one way that matters, and deliberately.**
The audit log drops a row and tells nobody, because a caller in the middle of
answering a customer can do nothing about it and a lost log line costs a record.
These tables hold the booking the customer is watching appear on a screen. A
write that vanished silently would leave the bot saying "your viewing is
confirmed" over an empty back office -- the single worst thing a demo can do. So
every call here raises `StoreUnavailable` instead, and the tool layer above turns
that into the same "I could not do that just now" the ERP tools already give.

Not an ORM, for the reason `requirements.txt` already gives about the audit
tables: a few CREATE TABLE statements and hand-written queries are not enough
surface to earn one and its migrations.
"""
from __future__ import annotations

import logging
import threading
import time

from app.config import settings
from app.services.mysql_url import connect as _default_connect
from app.services.mysql_url import dsn as _mysql_dsn

logger = logging.getLogger(__name__)

# Same posture as the audit log: once it has failed, stop paying the timeout on
# every request and try again in half a minute.
RETRY_AFTER_SECONDS = 30.0


class StoreUnavailable(RuntimeError):
    """The verticals database could not be reached, or is not configured.

    Raised rather than swallowed. What the caller does with it is the caller's
    business -- the tool layer answers the customer, a router answers 503 -- but
    it must not be possible to not notice.
    """


class VerticalsStore:
    """Where the property and food demos keep what the customer just did.

    One connection behind one lock, like the audit log: FastAPI runs these sync
    paths on its threadpool and a PyMySQL connection is not thread-safe, so the
    choice is a pool, a connection per thread, or a lock. At demo volume the lock
    is the one with no moving parts.
    """

    def __init__(self, url: str, connect=None) -> None:
        self._url = url
        self._connect = connect or _default_connect
        self._lock = threading.Lock()
        self._conn = None
        self._offline_until = 0.0
        self._schema_ready = False
        self._schema: list[str] = []

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def register(self, *statements: str) -> None:
        """Add a vertical's tables to the schema this store creates.

        Called at import time by each vertical, so the set is complete before any
        request arrives. Re-arms schema creation, so a vertical imported late --
        a test, or a router module loaded on first use -- still gets its tables
        rather than finding the schema already declared done without them.
        """
        with self._lock:
            self._schema.extend(statements)
            self._schema_ready = False

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run a write; returns the new row's id.

        Raises `StoreUnavailable` if it could not be run at all.
        """
        with self._lock:
            conn = self._connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.lastrowid
            except Exception as failure:
                raise self._go_offline("write failed", failure) from failure

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Read rows back.

        Raises `StoreUnavailable` rather than returning `[]`: an empty list is a
        real answer here -- no viewings booked yet -- and a database that is down
        must not be able to impersonate one.
        """
        import pymysql.cursors

        with self._lock:
            conn = self._connection()
            try:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
            except Exception as failure:
                raise self._go_offline("read failed", failure) from failure

    def reset(self) -> None:
        """Drop the connection and re-close the circuit. Tests."""
        with self._lock:
            self._conn = None
            self._offline_until = 0.0
            self._schema_ready = False

    def _connection(self):
        """A usable connection. Raises rather than returning None. Holds the lock."""
        if not self._url:
            raise StoreUnavailable("VERTICALS_MYSQL_URL is not set")
        if time.time() < self._offline_until:
            raise StoreUnavailable("the verticals database is unreachable")
        if self._conn is None:
            dsn = _mysql_dsn(self._url, feature="the verticals store")
            if dsn is None:
                # A malformed URL will not fix itself in thirty seconds, so this
                # one stays down until the process restarts with a good one.
                self._offline_until = float("inf")
                raise StoreUnavailable("VERTICALS_MYSQL_URL cannot be parsed")
            try:
                self._conn = self._connect(dsn)
            except Exception as failure:
                raise self._go_offline("could not connect", failure) from failure
        try:
            # Cheap, and the alternative is losing the first write after every
            # idle period longer than MySQL's wait_timeout -- which, between two
            # demos, is every one of them.
            self._conn.ping(reconnect=True)
        except Exception as failure:
            raise self._go_offline("ping failed", failure) from failure
        if not self._schema_ready:
            try:
                with self._conn.cursor() as cursor:
                    for statement in self._schema:
                        cursor.execute(statement)
                self._schema_ready = True
            except Exception as failure:
                raise self._go_offline("could not create the tables", failure) from failure
        return self._conn

    def _go_offline(self, reason: str, failure: Exception | None = None) -> StoreUnavailable:
        """Open the circuit, say why in one line, and hand back what to raise.

        One line rather than a traceback, for the reason the audit log gives: the
        driver's own message is the whole diagnosis and the frames above it are
        always the same path through pymysql. The caller raises the return value
        so that every exit from this class is visible at its call site.
        """
        self._conn = None
        self._schema_ready = False
        self._offline_until = time.time() + RETRY_AFTER_SECONDS
        logger.warning(
            "verticals database unavailable: %s%s",
            reason,
            f": {failure}" if failure else "",
        )
        return StoreUnavailable(reason)


# An empty VERTICALS_MYSQL_URL means the verticals have no back office, which is
# what the test suite and anyone running this without the shared infrastructure
# get. Unlike the audit log, that state is not silent: the first call says so.
store = VerticalsStore(settings.verticals_mysql_url)
