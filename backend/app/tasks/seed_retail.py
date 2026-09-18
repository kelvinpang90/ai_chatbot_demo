"""Which of the ERP's own trade accounts the seeded retail buyers are (task 39.3).

Retail is the one demo whose back office is not ours, so its seeded
conversations write nothing: `erp_os` reseeds a few hundred sales orders of its
own every night at 03:00, and a seeded buyer is simply the contact person of
one of those accounts, asking after orders that are already there. Everything
here is a read over the ERP's REST routes -- the rule that the ERP is only ever
reached through them (tasks/todo.md) holds for the seed as it does for the bot.

An account is only worth a conversation if its newest order falls inside the
seed's window. `erp_list_orders` answers with the account's newest orders as of
today, so a conversation dated before one of them would read out an order that
had not been placed yet; the conversation is dated after the newest instead,
and an account whose newest order is older than the window has nothing to say.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.services import erp_client, phone

# Newest first, so this many orders reach back well past the seed's four weeks
# on a book of ~250. One page is one request; the nightly run can afford it.
ORDERS_SCANNED = 100
CUSTOMERS_PAGE = 100


@dataclass(frozen=True)
class Account:
    customer_id: int
    company: str
    contact: str
    phone: str
    # The business date of the account's newest order.
    latest: date


def accounts(client: erp_client.ErpClient, *, now: float, days: int, wanted: int) -> list[Account]:
    """Up to `wanted` accounts whose newest order is inside the window, newest first.

    Raises `ApiClientError` when the ERP cannot be read. Nothing has been
    cleared by the time this runs, so a night the ERP is down leaves last
    night's batch where it was.
    """
    today = datetime.fromtimestamp(now).date()
    earliest = today - timedelta(days=days - 1)

    newest: dict[int, date] = {}
    orders = client.get("/api/sales-orders", params={"page_size": ORDERS_SCANNED}).get("items", [])
    for order in orders:
        customer_id = order.get("customer_id")
        try:
            ordered_on = date.fromisoformat(str(order.get("business_date")))
        except ValueError:
            continue
        if customer_id is not None and customer_id not in newest:
            newest[customer_id] = ordered_on

    book = {row.get("id"): row for row in _every_customer(client)}
    found = []
    for customer_id, latest in sorted(newest.items(), key=lambda item: item[1], reverse=True):
        row = book.get(customer_id)
        # Today's orders are left out: the conversation is dated after the
        # order, and there is no "after" that is not also in the quiet hour.
        if row is None or not (earliest <= latest < today):
            continue
        # The bot's own accounts are the ones the between-demos cleanup deletes.
        if str(row.get("code", "")).startswith(erp_client.CUSTOMER_CODE_PREFIX):
            continue
        if not row.get("contact_person") or not row.get("phone"):
            continue
        found.append(
            Account(
                customer_id=customer_id,
                company=str(row.get("name")),
                contact=str(row.get("contact_person")),
                phone=str(row.get("phone")),
                latest=latest,
            )
        )
        if len(found) >= wanted:
            break
    return found


def _every_customer(client: erp_client.ErpClient) -> list[dict]:
    # Capped the way `ErpClient` caps its own scans, so a route that ignored
    # `page` could not keep this asking forever.
    rows: list[dict] = []
    for page in range(1, phone.MAX_SCAN_PAGES + 1):
        payload = client.get("/api/customers", params={"page": page, "page_size": CUSTOMERS_PAGE})
        items = payload.get("items", [])
        rows.extend(items)
        if len(items) < CUSTOMERS_PAGE:
            break
    return rows
