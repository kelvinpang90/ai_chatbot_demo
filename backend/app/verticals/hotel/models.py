"""The resort's bookings table, and everything that reads or writes it.

A booking row holds the stay exactly as `tools/local.py` priced it off the room
catalogue -- rate, nights and total included -- so a rate edited in the JSON later
does not change what a guest was already quoted.

The booking number is the row id spelled `BK-00001`, never stored, for the reason
`food.models.order_no` gives. Every lookup a tool makes is by the customer the
channel established *and* that number, so a guest who reads out somebody else's
booking number finds nothing.

Read-only from the back office (user decision, 2026-09-17): the status is always
"Confirmed", because nobody at a demo checks a guest in.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel

from app.services.clock import sql_timestamp
from app.verticals.db import store

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS hotel_bookings (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        -- Whose booking this is, as the customer record is filed: the phone
        -- number, or the BSUID for a guest who hides it.
        customer_key VARCHAR(64) NOT NULL,
        customer_name VARCHAR(128) NOT NULL DEFAULT '',
        phone VARCHAR(32) NOT NULL DEFAULT '',
        location VARCHAR(64) NOT NULL,
        room_type VARCHAR(128) NOT NULL,
        check_in DATE NOT NULL,
        check_out DATE NOT NULL,
        nights INT UNSIGNED NOT NULL,
        guests INT UNSIGNED NOT NULL,
        rate_per_night_rm DECIMAL(10,2) NOT NULL,
        total_rm DECIMAL(10,2) NOT NULL,
        booked_at DATETIME(3) NOT NULL,
        updated_at DATETIME(3) NULL,
        PRIMARY KEY (id),
        KEY idx_customer (customer_key, booked_at),
        KEY idx_booked (booked_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

store.register(*SCHEMA)

CONFIRMED = "Confirmed"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
# A guest asking "what have I booked" wants their stays, not a history.
GUEST_LIMIT = 20

_NUMBER = re.compile(r"^\s*BK-0*(\d+)\s*$", re.IGNORECASE)


class Booking(BaseModel):
    """One row of the back office."""

    id: int
    booking_id: str
    customer_key: str
    customer_name: str
    phone: str
    location: str
    room_type: str
    check_in: str
    check_out: str
    nights: int
    guests: int
    rate_per_night_rm: float
    total_rm: float
    status: str
    # Naive local time, sliced by the page rather than parsed; see
    # tasks/erp-crm-timezone.md.
    booked_at: str
    updated_at: str | None = None

    def for_the_guest(self) -> dict:
        """What the model gets back: the stay, without whose record it is filed on."""
        return self.model_dump(exclude={"id", "customer_key", "customer_name", "phone"})


def booking_no(booking_id: int) -> str:
    return f"BK-{booking_id:05d}"


def row_id(number: str) -> int | None:
    """The row a booking number points at, or None if it is not one of ours."""
    match = _NUMBER.match(str(number or ""))
    return int(match.group(1)) if match else None


def book(*, customer_key: str, customer_name: str, phone: str, stay: dict, at: float) -> Booking:
    """Write one booking; returns it. Raises `StoreUnavailable`."""
    booked_at = sql_timestamp(at)
    row = {
        "customer_key": customer_key,
        "customer_name": customer_name.strip()[:128],
        "phone": phone.strip()[:32],
        **_stay_columns(stay),
        "booked_at": booked_at,
    }
    new_id = store.execute(
        "INSERT INTO hotel_bookings"
        " (customer_key, customer_name, phone, location, room_type, check_in, check_out,"
        "  nights, guests, rate_per_night_rm, total_rm, booked_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        tuple(row[column] for column in _INSERT_COLUMNS),
    )
    return _booking({**row, "id": new_id, "updated_at": None})


def change(booking: Booking, stay: dict, at: float) -> Booking:
    """Rewrite a booking's stay; returns it as it now stands. Raises `StoreUnavailable`.

    Guarded by the customer as well as the id, so the statement itself cannot
    touch a booking that is not theirs, whatever called it.
    """
    columns = _stay_columns(stay)
    updated_at = sql_timestamp(at)
    store.execute(
        "UPDATE hotel_bookings SET location = %s, room_type = %s, check_in = %s,"
        " check_out = %s, nights = %s, guests = %s, rate_per_night_rm = %s,"
        " total_rm = %s, updated_at = %s"
        " WHERE id = %s AND customer_key = %s",
        (
            *(columns[column] for column in _STAY_COLUMNS),
            updated_at,
            booking.id,
            booking.customer_key,
        ),
    )
    return _booking(
        {
            **booking.model_dump(),
            **columns,
            "updated_at": updated_at,
        }
    )


_SELECT = (
    "SELECT id, customer_key, customer_name, phone, location, room_type, check_in,"
    "  check_out, nights, guests, rate_per_night_rm, total_rm, booked_at, updated_at"
    " FROM hotel_bookings"
)


def bookings(limit: int = DEFAULT_LIMIT) -> list[Booking]:
    """The back office, newest first."""
    rows = store.query(
        _SELECT + " ORDER BY booked_at DESC, id DESC LIMIT %s",
        (max(1, min(limit, MAX_LIMIT)),),
    )
    return [_booking(row) for row in rows]


def bookings_for(customer_key: str, number: str = "") -> list[Booking]:
    """This guest's bookings, newest first -- or just the one they named, if it is theirs."""
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
            _SELECT + " WHERE customer_key = %s ORDER BY booked_at DESC, id DESC LIMIT %s",
            (customer_key, GUEST_LIMIT),
        )
    return [_booking(row) for row in rows]


_STAY_COLUMNS = (
    "location",
    "room_type",
    "check_in",
    "check_out",
    "nights",
    "guests",
    "rate_per_night_rm",
    "total_rm",
)
_INSERT_COLUMNS = ("customer_key", "customer_name", "phone", *_STAY_COLUMNS, "booked_at")


def _stay_columns(stay: dict) -> dict:
    return {
        "location": str(stay["location"])[:64],
        "room_type": str(stay["room_type"])[:128],
        "check_in": str(stay["check_in"]),
        "check_out": str(stay["check_out"]),
        "nights": int(stay["nights"]),
        "guests": int(stay["guests"]),
        # Through str, for the reason `food.models.subtotal_of` gives.
        "rate_per_night_rm": str(stay["rate_per_night_rm"]),
        "total_rm": str(stay["total_rm"]),
    }


def _booking(row: dict) -> Booking:
    return Booking(
        id=row["id"],
        booking_id=booking_no(row["id"]),
        customer_key=row["customer_key"],
        customer_name=row["customer_name"],
        phone=row["phone"],
        location=row["location"],
        room_type=row["room_type"],
        check_in=_day(row["check_in"]),
        check_out=_day(row["check_out"]),
        nights=int(row["nights"]),
        guests=int(row["guests"]),
        rate_per_night_rm=float(row["rate_per_night_rm"]),
        total_rm=float(row["total_rm"]),
        status=CONFIRMED,
        booked_at=_moment(row["booked_at"]),
        updated_at=_moment(row["updated_at"]) if row.get("updated_at") else None,
    )


def _day(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def _moment(value: datetime | str) -> str:
    # A row read back is a datetime; one just written is the string we sent.
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="milliseconds")
    return str(value)
