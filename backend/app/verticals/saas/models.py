"""The support tickets table, and everything that reads or writes it.

Shaped like `verticals/hotel/models.py`, for the same reasons: the ticket number
is the row id spelled `TCK-00001` and never stored, and every lookup a tool makes
is by the customer the channel established *and* that number, so a customer who
reads out somebody else's ticket number finds nothing.

Read-only from the back office (user decision, 2026-09-17): every ticket is
"open", because nobody works the queue during a demo.
"""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

from app.services.clock import sql_timestamp
from app.verticals.db import store

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS saas_tickets (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        -- Whose ticket this is, as the customer record is filed: the phone
        -- number, or the BSUID for a customer who hides it.
        customer_key VARCHAR(64) NOT NULL,
        customer_name VARCHAR(128) NOT NULL DEFAULT '',
        phone VARCHAR(32) NOT NULL DEFAULT '',
        subject VARCHAR(120) NOT NULL,
        description TEXT NOT NULL,
        priority VARCHAR(16) NOT NULL,
        opened_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_customer (customer_key, opened_at),
        KEY idx_opened (opened_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

store.register(*SCHEMA)

OPEN = "open"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
# A customer asking "what have I reported" wants their open issues, not a history.
CUSTOMER_LIMIT = 20

_NUMBER = re.compile(r"^\s*TCK-0*(\d+)\s*$", re.IGNORECASE)


class Ticket(BaseModel):
    """One row of the back office."""

    id: int
    ticket_id: str
    customer_key: str
    customer_name: str
    phone: str
    subject: str
    description: str
    priority: str
    status: str
    # Naive local time, sliced by the page rather than parsed; see
    # tasks/erp-crm-timezone.md.
    opened_at: str

    def for_the_customer(self) -> dict:
        """What the model gets back: the ticket, without whose record it is filed on."""
        return self.model_dump(exclude={"id", "customer_key", "customer_name", "phone"})


def ticket_no(ticket_id: int) -> str:
    return f"TCK-{ticket_id:05d}"


def row_id(number: str) -> int | None:
    """The row a ticket number points at, or None if it is not one of ours."""
    match = _NUMBER.match(str(number or ""))
    return int(match.group(1)) if match else None


def open_ticket(
    *,
    customer_key: str,
    customer_name: str,
    phone: str,
    subject: str,
    description: str,
    priority: str,
    at: float,
) -> Ticket:
    """Write one ticket; returns it. Raises `StoreUnavailable`."""
    row = {
        "customer_key": customer_key,
        "customer_name": customer_name.strip()[:128],
        "phone": phone.strip()[:32],
        "subject": subject,
        "description": description,
        "priority": priority,
        "opened_at": sql_timestamp(at),
    }
    new_id = store.execute(
        "INSERT INTO saas_tickets"
        " (customer_key, customer_name, phone, subject, description, priority, opened_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        tuple(row[column] for column in INSERT_COLUMNS),
    )
    return _ticket({**row, "id": new_id})


INSERT_COLUMNS = (
    "customer_key",
    "customer_name",
    "phone",
    "subject",
    "description",
    "priority",
    "opened_at",
)

_SELECT = (
    "SELECT id, customer_key, customer_name, phone, subject, description, priority, opened_at"
    " FROM saas_tickets"
)


def tickets(limit: int = DEFAULT_LIMIT) -> list[Ticket]:
    """The back office, newest first."""
    rows = store.query(
        _SELECT + " ORDER BY opened_at DESC, id DESC LIMIT %s",
        (max(1, min(limit, MAX_LIMIT)),),
    )
    return [_ticket(row) for row in rows]


def tickets_for(customer_key: str, number: str = "") -> list[Ticket]:
    """This customer's tickets, newest first -- or just the one they named, if it is theirs."""
    if number:
        wanted = row_id(number)
        if wanted is None:
            return []
        rows = store.query(
            _SELECT + " WHERE customer_key = %s AND id = %s LIMIT %s",
            (customer_key, wanted, 1),
        )
    else:
        rows = store.query(
            _SELECT + " WHERE customer_key = %s ORDER BY opened_at DESC, id DESC LIMIT %s",
            (customer_key, CUSTOMER_LIMIT),
        )
    return [_ticket(row) for row in rows]


def _ticket(row: dict) -> Ticket:
    return Ticket(
        id=row["id"],
        ticket_id=ticket_no(row["id"]),
        customer_key=row["customer_key"],
        customer_name=row["customer_name"],
        phone=row["phone"],
        subject=row["subject"],
        description=row["description"],
        priority=row["priority"],
        status=OPEN,
        opened_at=_moment(row["opened_at"]),
    )


def _moment(value: datetime | str) -> str:
    # A row read back is a datetime; one just written is the string we sent.
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="milliseconds")
    return str(value)
