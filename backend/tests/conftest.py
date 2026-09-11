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
from app.services import audit, crm_client, doc_store, erp_client, outbox
from app.services.user_store import user_store


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
