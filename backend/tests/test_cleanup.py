"""The between-demos cleanup: what it deletes, and everything it must not.

The tests patch the authenticated `get` / `post` / `delete`, so the paths a
route change would break are asserted rather than assumed -- the same boundary
the other back-office suites work at.
"""
from unittest.mock import patch

import pytest

from app.services import crm_client, erp_client
from app.services.api_client import ApiClientError
from app.tasks import cleanup

# What this bot wrote: a contact of its own, and a card it filed onto somebody
# who was already on the books.
BOT_CONTACT = {"id": "c-bot", "name": "Ahmad Faizal", "notes": "[DEMO] Opened by ..."}
BOT_CARD_ON_A_SEED_CONTACT = {"id": "d-bot", "title": "[DEMO] 3 units earbuds"}

# What the demo is shown against, and must survive every run.
SEED_CONTACT = {"id": "c-seed", "name": "David Park", "notes": "Met at KLCC expo"}
SEED_CARD = {"id": "d-seed", "title": "Annual hardware refresh"}

WA_CUSTOMER = {"id": 41, "code": "WA-60173948123-2609051423", "name": "Ahmad Faizal"}
SEED_CUSTOMER = {"id": 7, "code": "CUS-031", "name": "Sunrise Hypermart"}


class FakeCrm:
    """crm_os for the routes the cleanup uses."""

    def __init__(self, *, contacts, deals, delete_fails=None):
        self.contacts = list(contacts)
        self.deals = list(deals)
        self.delete_fails = delete_fails or {}
        self.deleted: list[str] = []

    def get(self, path, params=None):
        if path == "/api/contacts":
            # Page 1 holds everything; a short page is how the scan stops.
            return {"data": self.contacts if (params or {}).get("page", 1) == 1 else []}
        if path == "/api/deals":
            return self.deals
        raise AssertionError(f"unexpected GET {path}")

    def delete(self, path):
        for fragment, error in self.delete_fails.items():
            if fragment in path:
                raise error
        self.deleted.append(path)
        return {"success": True}


class FakeErp:
    """erp_os for the routes the cleanup uses, including the reset it waits on."""

    def __init__(self, *, customers, history=(), runs=(), delete_fails=None):
        self.customers = list(customers)
        self.history = list(history)
        # What `demo_reset_history` answers with after the reset is triggered,
        # one call at a time. Empty means the worker never picked the job up.
        self.runs = list(runs)
        self.delete_fails = delete_fails or {}
        self.deleted: list[str] = []
        self.triggered = 0
        self.searches: list[str | None] = []

    def get(self, path, params=None):
        params = params or {}
        if path == "/api/customers":
            self.searches.append(params.get("search"))
            return {"items": self.customers if params.get("page", 1) == 1 else []}
        if path == "/api/admin/demo-reset/history":
            if not self.triggered:
                return self.history
            return self.runs.pop(0) if self.runs else self.history
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, json=None):
        if path == "/api/admin/demo-reset":
            self.triggered += 1
            # The route answers this whether or not a worker is listening.
            return {"status": "queued", "demo_reset_log_id": 0}
        raise AssertionError(f"unexpected POST {path}")

    def delete(self, path):
        for fragment, error in self.delete_fails.items():
            if fragment in path:
                raise error
        self.deleted.append(path)
        return None  # erp_os answers a DELETE with 204 and no body


def _run(crm: FakeCrm, erp: FakeErp) -> cleanup.Report:
    crm_client.reset()
    erp_client.reset()
    with patch.object(crm_client.CrmClient, "get", side_effect=crm.get):
        with patch.object(crm_client.CrmClient, "delete", side_effect=crm.delete):
            with patch.object(erp_client.ErpClient, "get", side_effect=erp.get):
                with patch.object(erp_client.ErpClient, "post", side_effect=erp.post):
                    with patch.object(erp_client.ErpClient, "delete", side_effect=erp.delete):
                        report = cleanup.run()
    crm_client.reset()
    erp_client.reset()
    return report


def _succeeded(log_id=8):
    return [[{"id": log_id, "status": "SUCCESS", "error_message": None}]]


@pytest.fixture(autouse=True)
def _no_waiting():
    """Nothing here should sleep: every reset in this file resolves immediately."""
    with patch.object(cleanup, "RESET_POLL_SECONDS", 0):
        yield


def _crm(**kwargs):
    kwargs.setdefault("contacts", [SEED_CONTACT, BOT_CONTACT])
    kwargs.setdefault("deals", [SEED_CARD, BOT_CARD_ON_A_SEED_CONTACT])
    return FakeCrm(**kwargs)


def _erp(**kwargs):
    kwargs.setdefault("customers", [SEED_CUSTOMER, WA_CUSTOMER])
    kwargs.setdefault("runs", _succeeded())
    return FakeErp(**kwargs)


def test_a_clean_run_removes_what_the_bot_wrote_and_reports_it():
    crm, erp = _crm(), _erp()

    report = _run(crm, erp)

    assert crm.deleted == ["/api/deals/d-bot", "/api/contacts/c-bot"]
    assert erp.deleted == ["/api/customers/41"]
    assert erp.triggered == 1
    assert report.ok
    assert (report.cards_deleted, report.contacts_deleted, report.accounts_deleted) == (1, 1, 1)
    assert report.documents == "reset success"


def test_the_seed_data_the_demo_is_shown_against_is_never_touched():
    """The whole reason the mark exists. crm_os has no reset to undo a mistake here."""
    crm, erp = _crm(), _erp()

    _run(crm, erp)

    assert "/api/deals/d-seed" not in crm.deleted
    assert "/api/contacts/c-seed" not in crm.deleted
    assert "/api/customers/7" not in erp.deleted


def test_a_seed_contact_that_merely_mentions_the_mark_is_left_alone():
    """The mark is a prefix, not a substring: notes are written by people too."""
    chatty = {"id": "c-chatty", "name": "Siti", "notes": "Asked about the [DEMO] bot"}
    crm = _crm(contacts=[chatty], deals=[])

    _run(crm, _erp())

    assert crm.deleted == []


def test_a_card_on_a_seed_contact_is_deleted_without_the_contact():
    """The case the contact sweep cannot cover: the customer underneath is real."""
    crm = _crm(contacts=[SEED_CONTACT], deals=[BOT_CARD_ON_A_SEED_CONTACT])

    report = _run(crm, _erp())

    assert crm.deleted == ["/api/deals/d-bot"]
    assert report.cards_deleted == 1
    assert report.contacts_deleted == 0


def test_only_accounts_carrying_the_wa_code_are_retired():
    """`?search=` is an ILIKE over four columns, so it narrows and nothing more."""
    lookalike = {"id": 9, "code": "CUS-050", "name": "WA-Trading Sdn Bhd"}
    erp = _erp(customers=[lookalike, WA_CUSTOMER])

    report = _run(_crm(), erp)

    assert erp.deleted == ["/api/customers/41"]
    assert erp.searches == ["WA-"]
    assert report.accounts_deleted == 1


def test_a_queued_reset_nobody_ran_is_reported_as_a_failure():
    """The trap this stage exists for: the route answers `queued` with no worker.

    Reported green, this is a demo that opens on last week's orders.
    """
    erp = _erp(history=[{"id": 3, "status": "SUCCESS"}], runs=[])

    with patch.object(cleanup, "RESET_TIMEOUT_SECONDS", 0):
        report = _run(_crm(), erp)

    assert erp.triggered == 1
    assert not report.ok
    assert report.documents == "queued, never confirmed"
    assert "erp_celery_worker" in report.problems[0]


def test_a_reset_still_running_is_waited_for_rather_than_called_done():
    erp = _erp(
        runs=[
            [{"id": 8, "status": "RUNNING"}],
            [{"id": 8, "status": "SUCCESS", "error_message": None}],
        ]
    )

    report = _run(_crm(), erp)

    assert report.ok
    assert report.documents == "reset success"


def test_a_reset_that_failed_is_not_reported_as_a_reset():
    erp = _erp(runs=[[{"id": 8, "status": "FAILURE", "error_message": "Reseed failed: boom"}]])

    report = _run(_crm(), erp)

    assert not report.ok
    assert report.documents == "reset failure"
    assert "Reseed failed: boom" in report.problems[0]


def test_the_run_that_was_already_in_the_history_is_not_mistaken_for_this_one():
    """A reset truncates its own log table, so the history is short and reused ids
    are the obvious way to be fooled. Only a run this cleanup did not already see
    counts as an answer."""
    stale = {"id": 8, "status": "SUCCESS", "error_message": None}
    erp = _erp(history=[stale], runs=[[stale]])

    with patch.object(cleanup, "RESET_TIMEOUT_SECONDS", 0):
        report = _run(_crm(), erp)

    assert not report.ok
    assert report.documents == "queued, never confirmed"


def test_one_row_that_will_not_delete_does_not_stop_the_others():
    other_contact = {"id": "c-bot2", "name": "Lim", "notes": "[DEMO] Opened by ..."}
    crm = _crm(
        contacts=[BOT_CONTACT, other_contact],
        deals=[],
        delete_fails={"c-bot2": ApiClientError("crm api: DELETE returned 500")},
    )

    report = _run(crm, _erp())

    assert crm.deleted == ["/api/contacts/c-bot"]
    assert report.contacts_deleted == 1
    assert not report.ok
    assert "c-bot2" in report.problems[0]


def test_a_crm_that_is_down_does_not_cancel_the_erp_side():
    crm = FakeCrm(contacts=[], deals=[])
    crm.get = lambda path, params=None: (_ for _ in ()).throw(ApiClientError("crm api: down"))
    erp = _erp()

    report = _run(crm, erp)

    assert erp.deleted == ["/api/customers/41"]
    assert report.documents == "reset success"
    # Both CRM stages read, so both are reported: neither silently skipped.
    assert len(report.problems) == 2


def test_an_erp_that_is_down_is_reported_rather_than_raised():
    erp = _erp()
    erp.post = lambda path, json=None: (_ for _ in ()).throw(ApiClientError("erp api: down"))

    report = _run(_crm(), erp)

    assert not report.ok
    assert report.documents == "not reset"


def test_the_exit_status_says_whether_anything_went_wrong():
    """A cleanup nobody watched has to be answerable from the shell."""
    with patch.object(cleanup, "run", return_value=cleanup.Report()):
        assert cleanup.main() == 0
    with patch.object(cleanup, "run", return_value=cleanup.Report(problems=["nope"])):
        assert cleanup.main() == 1
