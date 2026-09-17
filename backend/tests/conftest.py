"""Fixtures shared by the back-office test modules.

The one thing that had to be shared: nothing under `backend/` sets ERP_EMAIL or
CRM_EMAIL, so `settings.*_email` is "" and both clients refuse at `_login`
before a byte reaches httpx. A test that patches httpx without one of these
fixtures is asserting against the missing-credentials path instead -- which is
how three ERP and three CRM transport cases sat green while covering nothing,
including the one standing guard over task 8's P1. Reviewed rounds 1 and 2 of
task 9.1.

Opt-in rather than autouse on purpose: a fixture that quietly handed every test
a logged-in client would only move the problem, and a test that wants the
no-credentials path (there is one) has to be able to ask for it.
"""
from unittest.mock import patch

import pytest

from app.config import settings
from app.console import events
from app.services import audit, crm_client, doc_store, erp_client, notify, outbox
from app.services.user_store import user_store
from app.session_store import session_store
from app.verticals import db as verticals_db
from app.verticals.hotel import models as hotel_models
from app.verticals.saas import models as saas_models


def _with_credentials(name, module):
    module.reset()
    with patch.object(settings, f"{name}_email", f"demo@{name}.test"):
        with patch.object(settings, f"{name}_password", "not-a-real-password"):
            yield
    module.reset()


@pytest.fixture
def erp_credentials():
    """An ERP client that will actually attempt a login."""
    yield from _with_credentials("erp", erp_client)


@pytest.fixture
def crm_credentials():
    """A CRM client that will actually attempt a login."""
    yield from _with_credentials("crm", crm_client)


@pytest.fixture(autouse=True)
def _no_outbox_left_open():
    """Every test starts with no channel for files, whatever the last one did.

    The outbox is a ContextVar, and production gets its isolation from the fact
    that each inbound message is handled in its own context. A test suite runs in
    one, so without this an outbox opened by any earlier test stays open, and the
    test that checks a channel with nowhere to put a PDF passes or fails
    depending on the file it happens to run after.
    """
    outbox.close()
    yield
    outbox.close()


@pytest.fixture(autouse=True)
def _no_audit_turn_left_open():
    """Every test starts outside a turn, whatever the last one did.

    The same ContextVar hazard the outbox has, and for the same reason: in
    production each inbound message is handled in its own context, while a test
    suite runs in one. Without this, a turn opened by any earlier test stays
    open, and a test asserting that something is *not* recorded passes or fails
    depending on which file it happens to run after.
    """
    audit.close()
    audit.audit_store.reset()
    yield
    audit.close()
    audit.audit_store.reset()


@pytest.fixture(autouse=True)
def _no_verticals_connection_left_open():
    """The shared verticals store starts every test cold.

    It holds a connection and an open-or-closed circuit across calls, so a test
    that knocked it offline would otherwise decide what the next file sees --
    and that store raises, so the symptom is an unrelated test erroring rather
    than quietly reading nothing.
    """
    verticals_db.store.reset()
    yield
    verticals_db.store.reset()


@pytest.fixture(autouse=True)
def _no_customers_on_file():
    """Every test starts against a store that has never met anyone.

    REDIS_URL is unset under pytest, so the shared `user_store` keeps its
    profiles in a process-wide dictionary that would otherwise outlive the test
    that wrote them. Since task 32 that dictionary decides which demo a number
    is already in, so a stale entry is the difference between "shown the menu"
    and "answered by the retail bot" in a test that never mentioned either.
    """
    user_store.reset()
    yield
    user_store.reset()


@pytest.fixture(autouse=True)
def _no_documents_on_file():
    """Every test starts with nobody having sent a file.

    `doc_store` lives in the process rather than in Redis -- which is the whole
    point of it -- so a PDF filed by one test is still attached to that customer
    in the next one. Distinct phone numbers per test hide this until the day two
    tests share one.
    """
    doc_store.clear()
    yield
    doc_store.clear()


@pytest.fixture(autouse=True)
def _no_message_already_seen():
    """Every test starts with no WhatsApp message id handled and nothing counted.

    Found 2026-09-14 when a new test file made an old test fail only in the full
    run: both sent `wamid.60129996002.1`, the first one got there first, and the
    old test's second message was skipped as a duplicate -- so the model never saw
    the question the test was about. Any two tests reusing a message id interfered
    that way, and which one lost depended on the order the files ran in. The
    per-number daily count had the same shape, just further from the cap.
    """
    session_store.reset()
    yield
    session_store.reset()


@pytest.fixture(autouse=True)
def _no_customer_left_on_the_console():
    """Every test starts emitting console events on behalf of nobody.

    The same ContextVar hazard as the outbox: in production each inbound message
    is handled in its own context, while a test suite runs in one. Without this,
    the last WhatsApp message any earlier test dispatched would decide whose name
    goes on the events of a test that never mentioned a customer.
    """
    events.clear_customer()
    yield
    events.clear_customer()


@pytest.fixture(autouse=True)
def _no_push_queue_left_open():
    """Every test starts in a conversation that cannot be followed up.

    The same ContextVar hazard the outbox has: a queue opened by any earlier test
    stays open for the rest of the suite, and a tool that checks
    `notify.available()` to decide whether it is on WhatsApp would then believe
    it always is -- including in the web chat tests, which is exactly the case
    that check exists to catch.
    """
    notify.close()
    yield
    notify.close()


class FakeHotelStore:
    """Enough of MySQL for the statements `verticals/hotel/models.py` writes.

    Shared rather than kept in one module, unlike the food and property stand-ins,
    because two modules drive it: the tools that book (`test_local_tools.py`) and
    the back office that lists (`test_verticals_hotel.py`). Rows are held in the
    types PyMySQL hands back -- `date`, `Decimal`, `datetime` -- so the reading
    side is exercised on what it will really get.
    """

    def __init__(self, fails: bool = False):
        self.rows: list[dict] = []
        self.fails = fails

    def execute(self, sql: str, params: tuple = ()) -> int:
        if self.fails:
            raise verticals_db.StoreUnavailable("the verticals database is unreachable")
        if sql.startswith("INSERT INTO hotel_bookings"):
            row = self._typed(dict(zip(hotel_models._INSERT_COLUMNS, params)))
            row["updated_at"] = None
            row["id"] = len(self.rows) + 1
            self.rows.append(row)
            return row["id"]
        if sql.startswith("UPDATE hotel_bookings"):
            *stay, updated_at, row_id, customer_key = params
            for row in self.rows:
                if row["id"] == row_id and row["customer_key"] == customer_key:
                    row.update(self._typed(dict(zip(hotel_models._STAY_COLUMNS, stay))))
                    row["updated_at"] = _moment(updated_at)
            return 0
        raise AssertionError(f"unexpected statement: {sql}")

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.fails:
            raise verticals_db.StoreUnavailable("the verticals database is unreachable")
        rows = sorted(self.rows, key=lambda row: (row["booked_at"], row["id"]), reverse=True)
        if "WHERE customer_key = %s AND id = %s" in sql:
            rows = [row for row in rows if (row["customer_key"], row["id"]) == params[:2]]
        elif "WHERE customer_key = %s" in sql:
            rows = [row for row in rows if row["customer_key"] == params[0]]
        return [dict(row) for row in rows[: params[-1]]]

    @staticmethod
    def _typed(row: dict) -> dict:
        from datetime import date
        from decimal import Decimal

        for column in ("check_in", "check_out"):
            if column in row:
                row[column] = date.fromisoformat(row[column])
        for column in ("rate_per_night_rm", "total_rm"):
            if column in row:
                row[column] = Decimal(row[column])
        if "booked_at" in row:
            row["booked_at"] = _moment(row["booked_at"])
        return row


def _moment(text: str):
    from datetime import datetime

    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")


@pytest.fixture
def hotel_store():
    """The resort's bookings table, in memory."""
    store = FakeHotelStore()
    with patch.object(hotel_models, "store", store):
        yield store


class FakeSaasStore:
    """Enough of MySQL for the statements `verticals/saas/models.py` writes."""

    def __init__(self, fails: bool = False):
        self.rows: list[dict] = []
        self.fails = fails

    def execute(self, sql: str, params: tuple = ()) -> int:
        if self.fails:
            raise verticals_db.StoreUnavailable("the verticals database is unreachable")
        if not sql.startswith("INSERT INTO saas_tickets"):
            raise AssertionError(f"unexpected statement: {sql}")
        row = dict(zip(saas_models.INSERT_COLUMNS, params))
        row["opened_at"] = _moment(row["opened_at"])
        row["id"] = len(self.rows) + 1
        self.rows.append(row)
        return row["id"]

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.fails:
            raise verticals_db.StoreUnavailable("the verticals database is unreachable")
        rows = sorted(self.rows, key=lambda row: (row["opened_at"], row["id"]), reverse=True)
        if "WHERE customer_key = %s AND id = %s" in sql:
            rows = [row for row in rows if (row["customer_key"], row["id"]) == params[:2]]
        elif "WHERE customer_key = %s" in sql:
            rows = [row for row in rows if row["customer_key"] == params[0]]
        return [dict(row) for row in rows[: params[-1]]]


@pytest.fixture
def saas_store():
    """The support desk's tickets table, in memory."""
    store = FakeSaasStore()
    with patch.object(saas_models, "store", store):
        yield store
