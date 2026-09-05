"""Put the two back offices back the way the next demo wants to find them.

Run between demos, on the VPS where the credentials are:

    docker exec ai_chatbot_backend python -m app.tasks.cleanup

It talks to both back offices over HTTPS like everything else here, so it runs
anywhere a `.env` with the two accounts does.

Four kinds of leftovers, and only three of them need doing here.

Redis is the one that does not: a customer profile carries a seven-day rolling
TTL, so a number that stops writing forgets itself. That is deliberate rather
than lazy -- the profile is the thing that lets a customer come back tomorrow
and be recognised, and a cleanup that cleared it would delete the feature.

The other three are cleared here, each by a rule narrow enough that it cannot
reach the seed data the demo is shown against:

  * CRM cards this bot filed onto a customer who was already on the books --
    deleted one at a time, because the customer must stay.
  * CRM contacts this bot opened -- deleted whole, cards and all.
  * ERP trade accounts this bot opened -- deleted by their `WA-` code prefix.
    erp_os's own demo reset does not touch `customers`, so without this they
    accumulate one per demo forever.

and one that is asked for rather than performed: the ERP's transactional
documents. Orders here reach FULLY_SHIPPED and INVOICED, and erp_os has no
route that deletes or cancels either, so `POST /api/admin/demo-reset` is the
only way -- see `_reset_documents` for why its answer is not evidence.

A stage that fails does not stop the ones after it, and the exit status is
non-zero if anything at all went wrong. Half a cleanup reported as a success is
how a demo starts against data nobody expected.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field

from app.services import crm_client, erp_client
from app.services.api_client import ApiClientError

logger = logging.getLogger(__name__)

# The reset truncates fifteen-odd tables and reseeds stock behind a Celery
# worker, so it is neither instant nor slow enough to walk away from.
RESET_TIMEOUT_SECONDS = 180
RESET_POLL_SECONDS = 3

# What `DemoResetStatus` calls a run that is over, whichever way it went
# (`erp_os/backend/app/enums.py:237`). Anything else means still running.
RESET_FINISHED = ("SUCCESS", "FAILURE", "ROLLED_BACK")


@dataclass
class Report:
    """What the run did, and everything that went wrong while it did it."""

    cards_deleted: int = 0
    contacts_deleted: int = 0
    accounts_deleted: int = 0
    documents: str = "not attempted"
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        summary = [
            f"CRM cards deleted:     {self.cards_deleted}",
            f"CRM contacts deleted:  {self.contacts_deleted}",
            f"ERP accounts deleted:  {self.accounts_deleted}",
            f"ERP documents:         {self.documents}",
        ]
        if self.problems:
            summary.append("")
            summary.append(f"{len(self.problems)} problem(s):")
            summary.extend(f"  - {problem}" for problem in self.problems)
        return summary


def _clear_crm_cards(client: crm_client.CrmClient, report: Report) -> None:
    """Delete the cards this bot filed onto customers who were already here.

    These are the ones that cannot be cleared by deleting a contact: the
    customer underneath is seed data, and the demo is shown against them.

    Run before the contacts rather than after. The other order works -- deleting
    a contact cascades to its cards -- but it would spend a request per card
    finding out the card was already gone.
    """
    for deal in client.all_deals():
        if not crm_client.is_marked(deal.get("title")):
            continue
        try:
            client.delete_deal(deal["id"])
        except ApiClientError as exc:
            report.problems.append(f"CRM card {deal.get('id')} was not deleted: {exc}")
            continue
        report.cards_deleted += 1


def _clear_crm_contacts(client: crm_client.CrmClient, report: Report) -> None:
    """Delete the contacts this bot opened, each taking its own cards with it."""
    for contact in client.all_contacts():
        if not crm_client.is_marked(contact.get("notes")):
            continue
        try:
            client.delete_contact(contact["id"])
        except ApiClientError as exc:
            report.problems.append(f"CRM contact {contact.get('id')} was not deleted: {exc}")
            continue
        report.contacts_deleted += 1


def _clear_erp_accounts(client: erp_client.ErpClient, report: Report) -> None:
    """Retire the trade accounts opened over WhatsApp."""
    for customer in client.demo_customers():
        try:
            client.delete_customer(customer["id"])
        except ApiClientError as exc:
            report.problems.append(
                f"ERP account {customer.get('code')} was not deleted: {exc}"
            )
            continue
        report.accounts_deleted += 1


def _reset_documents(client: erp_client.ErpClient, report: Report) -> None:
    """Ask erp_os to wipe its documents, then find out whether it did.

    The two steps are not the same step. `POST /api/admin/demo-reset` enqueues a
    Celery job and answers `status: queued` either way, so with no worker
    running it reports a success that never happens -- the reason this waits on
    the history instead. A run that is still going when the wait runs out is
    reported as exactly that, because it may well finish afterwards.

    What comes back is a reseeded ERP rather than an empty one: the reset also
    re-runs `seed_initial_stock` and `seed_transactional`, so the products keep
    their stock and the seeded orders return. `skus` and `customers` are not in
    `RESET_TABLES` at all, which is why a hand-made SKU survives this.
    """
    already_seen = {row.get("id") for row in client.demo_reset_history()}
    client.start_demo_reset()

    deadline = time.monotonic() + RESET_TIMEOUT_SECONDS
    while True:
        reset_run = next(
            (
                row
                for row in client.demo_reset_history()
                if row.get("id") not in already_seen
            ),
            None,
        )
        if reset_run is not None and str(reset_run.get("status")) in RESET_FINISHED:
            break
        if time.monotonic() >= deadline:
            report.problems.append(
                "ERP documents: no finished reset appeared in "
                f"/api/admin/demo-reset/history within {RESET_TIMEOUT_SECONDS}s. "
                "The job was queued; check that erp_celery_worker is running."
            )
            report.documents = "queued, never confirmed"
            return
        time.sleep(RESET_POLL_SECONDS)

    status = str(reset_run.get("status"))
    report.documents = f"reset {status.lower()}"
    if status != "SUCCESS":
        report.problems.append(
            f"ERP documents: the reset finished {status} -- {reset_run.get('error_message')}"
        )


def run() -> Report:
    """Clear both back offices, and say what happened."""
    report = Report()

    crm = crm_client.client()
    try:
        _clear_crm_cards(crm, report)
    except ApiClientError as exc:
        report.problems.append(f"the CRM pipeline could not be read: {exc}")

    try:
        _clear_crm_contacts(crm, report)
    except ApiClientError as exc:
        report.problems.append(f"the CRM contact book could not be read: {exc}")

    erp = erp_client.client()
    try:
        _clear_erp_accounts(erp, report)
    except ApiClientError as exc:
        report.problems.append(f"ERP accounts could not be cleared: {exc}")

    try:
        _reset_documents(erp, report)
    except ApiClientError as exc:
        report.problems.append(f"ERP documents could not be reset: {exc}")
        report.documents = "not reset"

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    report = run()
    print("\n".join(report.lines()))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
