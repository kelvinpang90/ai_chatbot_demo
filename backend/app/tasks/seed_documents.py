"""The documents a seeded conversation ends in, filed where the demo shows them (task 39.2).

A food order, a hotel booking, a support ticket and a property viewing, each
written through the vertical's own model function -- the one the live tool
calls -- with the moment it happened passed in. So the totals, the kitchen's
timeline and the back office's row are what a real order would have made, and
`/admin` lists them in among the real ones on the day the conversation says.

Clearing is by the same rule as the audit log -- the seed's own customer keys --
except for the viewings table, which has no customer column to carry one: a
viewing is a name and a phone number. Rather than spell a marker into either of
those (which `/admin` shows), the ids this seed filed are kept in a table of
its own, `seed_console_viewings`, and cleared through it.

The verticals store raises `StoreUnavailable` rather than dropping a row, which
is what a seed wants; nothing here catches it.
"""
from __future__ import annotations

from datetime import date

from app.config import settings
from app.verticals.db import store
from app.verticals.food import models as food_models
from app.verticals.hotel import models as hotel_models
from app.verticals.realestate import models as realestate_models
from app.verticals.saas import models as saas_models

LEDGER_SCHEMA = """
    CREATE TABLE IF NOT EXISTS seed_console_viewings (
        viewing_id BIGINT UNSIGNED NOT NULL,
        PRIMARY KEY (viewing_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

store.register(LEDGER_SCHEMA)

_KEYED_TABLES = ("food_orders", "hotel_bookings", "saas_tickets")


class Filer:
    """Writes each document and says what it filed. Swapped for a fake in tests."""

    def __init__(self) -> None:
        self.filed = 0

    def food_order(
        self, *, key_id: str, name: str, lines: list[food_models.OrderLine], address: str, fee, at: float
    ) -> int:
        order_id = food_models.place_order(
            customer_key=key_id,
            customer_name=name,
            phone="",
            delivery_address=address,
            lines=lines,
            delivery_fee_rm=fee,
            ready_after_seconds=settings.push_delay_seconds,
            at=at,
        )
        self.filed += 1
        return order_id

    def hotel_booking(self, *, key_id: str, name: str, stay: dict, at: float) -> hotel_models.Booking:
        booking = hotel_models.book(customer_key=key_id, customer_name=name, phone="", stay=stay, at=at)
        self.filed += 1
        return booking

    def ticket(
        self, *, key_id: str, name: str, subject: str, description: str, priority: str, at: float
    ) -> saas_models.Ticket:
        ticket = saas_models.open_ticket(
            customer_key=key_id,
            customer_name=name,
            phone="",
            subject=subject,
            description=description,
            priority=priority,
            at=at,
        )
        self.filed += 1
        return ticket

    def viewing(
        self, *, name: str, listing_id: str, viewing_date: date, preferred_time: str, at: float
    ) -> realestate_models.Viewing:
        # The join in `get_viewing` needs the listings in the table.
        realestate_models.seed_listings()
        viewing_id = realestate_models.book_viewing(
            realestate_models.ViewingRequest(
                listing_id=listing_id,
                customer_name=name,
                viewing_date=viewing_date,
                preferred_time=preferred_time,
            ),
            at=at,
        )
        store.execute("INSERT INTO seed_console_viewings (viewing_id) VALUES (%s)", (viewing_id,))
        self.filed += 1
        return realestate_models.get_viewing(viewing_id)


def clear(prefix: str) -> None:
    """Delete every document a previous seed filed, and nothing else."""
    for table in _KEYED_TABLES:
        store.execute(f"DELETE FROM {table} WHERE customer_key LIKE %s", (f"{prefix}%",))
    store.execute(
        "DELETE v FROM realestate_viewings v JOIN seed_console_viewings s ON s.viewing_id = v.id"
    )
    store.execute("DELETE FROM seed_console_viewings")
