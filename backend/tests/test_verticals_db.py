"""The verticals' database (task 22).

Driven against a fake DB-API connection, like test_audit.py, so the SQL and the
parameters are asserted as written rather than mocked away. What that cannot
check is whether MySQL accepts the statements -- that is the live run against a
real mysql:8 recorded in tasks/todo.md, via scripts/verticals_probe.py.

Most of these guard the one place this store deliberately parts company with the
audit log: it raises. A booking that silently went nowhere would leave the bot
telling a customer their viewing is confirmed over an empty back office.
"""
import time
from unittest.mock import patch

import pytest

from app.verticals import db
from app.verticals.db import RETRY_AFTER_SECONDS, StoreUnavailable, VerticalsStore

URL = "mysql://chatbot:chatbot@mysql:3306/ai_chatbot_verticals"

TABLE = """
    CREATE TABLE IF NOT EXISTS viewings (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


class FakeCursor:
    def __init__(self, conn, rows=None):
        self._conn = conn
        self._rows = rows or []
        self.lastrowid = 0

    def execute(self, sql, params=()):
        if self._conn.fail_on and self._conn.fail_on in sql:
            raise RuntimeError("mysql said no")
        self._conn.statements.append((sql.strip(), params))
        self._conn.executed += 1
        self.lastrowid = self._conn.executed

    def fetchall(self):
        return self._conn.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, fail_on: str = "", rows=None, ping_fails: bool = False):
        self.statements: list[tuple[str, tuple]] = []
        self.executed = 0
        self.fail_on = fail_on
        self.rows = rows or []
        self.ping_fails = ping_fails
        self.pings = 0

    def cursor(self, *args, **kwargs):
        return FakeCursor(self)

    def ping(self, reconnect=False):
        self.pings += 1
        if self.ping_fails:
            raise RuntimeError("gone away")


def _store(conn=None, url: str = URL, schema=(TABLE,), **kwargs):
    conn = conn or FakeConnection(**kwargs)
    store = VerticalsStore(url, connect=lambda dsn: conn)
    store.register(*schema)
    return store, conn


def _creates(conn):
    return [sql for sql, _ in conn.statements if sql.startswith("CREATE TABLE")]


# --- it raises, where the audit log would not ---------------------------------


def test_an_unset_url_raises_rather_than_going_quietly_dark():
    """The whole difference from the audit log in one test. A log that cannot
    write costs a record; a booking that cannot write costs a customer who was
    told it worked."""
    store, _ = _store(url="")
    assert store.enabled is False
    with pytest.raises(StoreUnavailable):
        store.execute("INSERT INTO viewings () VALUES ()")


def test_a_write_that_fails_raises():
    store, _ = _store(fail_on="INSERT")
    with pytest.raises(StoreUnavailable):
        store.execute("INSERT INTO viewings () VALUES ()")


def test_a_read_that_fails_raises_rather_than_answering_empty():
    """An empty list is a real answer here -- nobody has booked yet -- so a
    database that is down must not be able to impersonate one."""
    store, _ = _store(fail_on="SELECT")
    with pytest.raises(StoreUnavailable):
        store.query("SELECT * FROM viewings")


def test_a_connection_that_cannot_be_opened_raises():
    store = VerticalsStore(URL, connect=lambda dsn: (_ for _ in ()).throw(RuntimeError("down")))
    store.register(TABLE)
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")


def test_a_dead_connection_is_noticed_by_the_ping():
    """MySQL closes an idle connection, and between two demos every connection
    is idle for longer than wait_timeout."""
    store, conn = _store(ping_fails=True)
    with pytest.raises(StoreUnavailable):
        store.execute("INSERT INTO viewings () VALUES ()")
    assert conn.pings == 1


def test_a_malformed_url_raises():
    store, conn = _store(url="postgres://u:p@host/db")
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")
    assert conn.statements == []


def test_a_malformed_url_is_parsed_once_and_not_retried():
    """A typo will not fix itself in thirty seconds, or ever.

    Counting parses rather than statements: a url that cannot be parsed never
    reaches the driver either way, so "nothing was executed" would pass whether
    or not the circuit latched.
    """
    store, _ = _store(url="postgres://u:p@host/db")
    parses = 0
    real = db._mysql_dsn

    def counting(url, *, feature):
        nonlocal parses
        parses += 1
        return real(url, feature=feature)

    with patch.object(db, "_mysql_dsn", counting):
        for _ in range(3):
            with pytest.raises(StoreUnavailable):
                store.query("SELECT 1")
    assert parses == 1


# --- reading and writing ------------------------------------------------------


def test_a_write_returns_the_new_row_id():
    store, _ = _store()
    assert store.execute("INSERT INTO viewings () VALUES ()") == 2  # after the CREATE


def test_the_parameters_are_passed_to_the_driver_not_interpolated():
    """Hand-written SQL with %s placeholders, like the audit log. A name with an
    apostrophe in it is a customer, not a syntax error."""
    store, conn = _store()
    store.execute("INSERT INTO viewings (name) VALUES (%s)", ("O'Brien",))
    sql, params = conn.statements[-1]
    assert params == ("O'Brien",)
    assert "O'Brien" not in sql


def test_a_read_comes_back_as_dicts():
    store, _ = _store(rows=[{"id": 1, "name": "Taman Perling"}])
    assert store.query("SELECT * FROM viewings") == [{"id": 1, "name": "Taman Perling"}]


# --- the schema ---------------------------------------------------------------


def test_the_schema_is_created_once_not_per_call():
    store, conn = _store()
    store.execute("INSERT INTO viewings () VALUES ()")
    store.execute("INSERT INTO viewings () VALUES ()")
    assert len(_creates(conn)) == 1


def test_every_registered_vertical_gets_its_tables():
    """Two verticals share one connection; neither may create only its own."""
    other = "CREATE TABLE IF NOT EXISTS orders (id INT) ENGINE=InnoDB"
    store, conn = _store(schema=(TABLE, other))
    store.query("SELECT 1")
    assert len(_creates(conn)) == 2


def test_a_vertical_registered_late_still_gets_its_tables():
    """A module imported after the first query -- a router loaded on first use,
    or a test -- must not find the schema already declared done without it."""
    store, conn = _store()
    store.query("SELECT 1")
    store.register("CREATE TABLE IF NOT EXISTS orders (id INT) ENGINE=InnoDB")
    store.query("SELECT 1")
    assert len(_creates(conn)) == 3  # the first table twice, IF NOT EXISTS, plus the new one


def test_a_store_nobody_registered_anything_with_still_works():
    """Task 22 ships the connection and no tables of its own."""
    store, conn = _store(schema=())
    store.query("SELECT 1")
    assert _creates(conn) == []


# --- the circuit --------------------------------------------------------------


def test_a_failure_opens_the_circuit_for_half_a_minute():
    """Raising is not a reason to pay the connect timeout on every request."""
    store, conn = _store(ping_fails=True)
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")
    assert conn.pings == 1


def test_the_circuit_closes_again_afterwards():
    store, conn = _store()
    conn.ping_fails = True
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")

    conn.ping_fails = False
    with patch.object(time, "time", return_value=time.time() + RETRY_AFTER_SECONDS + 1):
        store.query("SELECT 1")
    assert conn.pings == 2


def test_the_schema_is_rebuilt_after_a_reconnect():
    """The tables may be gone with the database that went away."""
    store, conn = _store()
    store.query("SELECT 1")
    conn.ping_fails = True
    with pytest.raises(StoreUnavailable):
        store.query("SELECT 1")

    conn.ping_fails = False
    with patch.object(time, "time", return_value=time.time() + RETRY_AFTER_SECONDS + 1):
        store.query("SELECT 1")
    assert len(_creates(conn)) == 2


def test_the_failure_says_which_database_went_dark(caplog):
    """One line, no traceback: the driver's own message is the whole diagnosis."""
    store, _ = _store(fail_on="INSERT")
    with caplog.at_level("WARNING"), pytest.raises(StoreUnavailable):
        store.execute("INSERT INTO viewings () VALUES ()")
    assert "verticals database unavailable" in caplog.text
    assert "mysql said no" in caplog.text
