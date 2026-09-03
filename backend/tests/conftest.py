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
from app.services import crm_client, erp_client, outbox


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
