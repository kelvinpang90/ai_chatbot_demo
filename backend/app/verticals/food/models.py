"""The restaurant's orders table, and everything that reads or writes it.

**The kitchen is a timeline, written down when the order is placed.** There is
no cook to tap "ready" during a demo, and scene 3 needs the phone to buzz with
"your food is on its way" while nobody touches anything. The obvious build -- a
status column and a timer that moves it along -- has two clocks that have to
agree: the timer that flips the row and the one that sends the push. If either
is lost to a restart, or the database is down for the second it fires, the
customer reads "on its way" over a back office that still says "preparing".

So the order row carries the moment each stage begins, and the status is read
off the clock by whoever asks. The push that says the food has left is queued
for exactly `ready_at`, so by the time it can arrive the row already says so --
not because two things happened to line up, but because there is one thing.
The times are fixed when the order is placed, so changing the push delay in
`.env` later does not rewrite what an old order said.

**The menu is not a table.** It is `bots/data/food.json`, which is also what the
model reads the dishes and prices from. A second copy in here would be free to
disagree -- the listings in the property vertical are seeded for a back office
that shows them; nobody needs to see the menu on this screen. Each order keeps
its own copy of the lines it was placed with, prices included, so an edited
price in the JSON does not change a bill that has already been paid.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.services.clock import sql_timestamp
from app.verticals.db import store

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS food_orders (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        -- Whose order this is, as the customer record is filed: the phone number,
        -- or the BSUID for a customer who hides it. What "where is my order"
        -- looks up by, so the model never gets to name somebody else's.
        customer_key VARCHAR(64) NOT NULL,
        customer_name VARCHAR(128) NOT NULL DEFAULT '',
        phone VARCHAR(32) NOT NULL DEFAULT '',
        delivery_address VARCHAR(255) NOT NULL,
        -- The dishes as they were ordered, prices included, in the one INSERT
        -- that creates the order. A second lines table would be a second write,
        -- and an order row that made it without its lines is an empty bill on
        -- the screen in the middle of the scene about the bill.
        order_lines JSON NOT NULL,
        subtotal_rm DECIMAL(10,2) NOT NULL,
        delivery_fee_rm DECIMAL(10,2) NOT NULL,
        total_rm DECIMAL(10,2) NOT NULL,
        placed_at DATETIME(3) NOT NULL,
        preparing_at DATETIME(3) NOT NULL,
        ready_at DATETIME(3) NOT NULL,
        delivered_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        KEY idx_customer (customer_key, placed_at),
        KEY idx_placed (placed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

store.register(*SCHEMA)

# The four stages, in order, with the column each one starts at.
RECEIVED = "received"
PREPARING = "preparing"
ON_THE_WAY = "on_the_way"
DELIVERED = "delivered"

# How long the order sits as "received" before the kitchen has it. A few seconds,
# so the first poll of the back office catches the order arriving rather than
# already cooking -- and never more than half the time to the kitchen door, so a
# rehearsal with PUSH_DELAY_SECONDS=4 still shows all four stages.
RECEIVED_SECONDS = 10.0

# How long the rider takes, which is also the number in the push. Ten minutes is
# scene 3's line ("骑手预计 10 分钟送达") and a believable ride inside the 8 km
# the menu promises.
RIDER_MINUTES = 10

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class OrderLine(BaseModel):
    item_id: str
    name: str
    unit_price_rm: float
    quantity: int


class Order(BaseModel):
    """One row of the back office, with its status as of `now`."""

    id: int
    order_no: str
    customer_key: str
    customer_name: str
    phone: str
    delivery_address: str
    lines: list[OrderLine]
    subtotal_rm: float
    delivery_fee_rm: float
    total_rm: float
    status: str
    # Naive local time, sliced by the page rather than parsed; see
    # `realestate.models._text` and tasks/erp-crm-timezone.md.
    placed_at: str
    preparing_at: str
    ready_at: str
    delivered_at: str


def order_no(order_id: int) -> str:
    """What the customer and the screen call an order. Derived, never stored:
    two spellings of the same id cannot disagree if there is only one."""
    return f"FD-{order_id:05d}"


def timeline(placed: float, ready_after_seconds: float) -> dict[str, float]:
    """When each stage of an order placed at `placed` begins, as epoch seconds."""
    ready_after = max(0.0, ready_after_seconds)
    return {
        "placed_at": placed,
        "preparing_at": placed + min(RECEIVED_SECONDS, ready_after / 2),
        "ready_at": placed + ready_after,
        "delivered_at": placed + ready_after + RIDER_MINUTES * 60,
    }


def status_at(order: dict, now: datetime) -> str:
    """Which stage an order is in at `now`. `order` holds the four datetimes."""
    if now >= order["delivered_at"]:
        return DELIVERED
    if now >= order["ready_at"]:
        return ON_THE_WAY
    if now >= order["preparing_at"]:
        return PREPARING
    return RECEIVED


def subtotal_of(lines: list[OrderLine]) -> Decimal:
    # Through str: Decimal(12.9) is 12.9000000000000003552713678800500929355621337890625.
    return sum((Decimal(str(line.unit_price_rm)) * line.quantity for line in lines), Decimal("0"))


def place_order(
    *,
    customer_key: str,
    customer_name: str,
    phone: str,
    delivery_address: str,
    lines: list[OrderLine],
    delivery_fee_rm: Decimal,
    ready_after_seconds: float,
    at: float,
) -> int:
    """Write one order; returns its id. Raises `StoreUnavailable`."""
    subtotal = subtotal_of(lines)
    stages = timeline(at, ready_after_seconds)
    return store.execute(
        "INSERT INTO food_orders"
        " (customer_key, customer_name, phone, delivery_address, order_lines,"
        "  subtotal_rm, delivery_fee_rm, total_rm,"
        "  placed_at, preparing_at, ready_at, delivered_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            customer_key,
            customer_name.strip()[:128],
            phone.strip()[:32],
            delivery_address.strip()[:255],
            json.dumps([line.model_dump() for line in lines], ensure_ascii=False),
            str(subtotal),
            str(delivery_fee_rm),
            str(subtotal + delivery_fee_rm),
            sql_timestamp(stages["placed_at"]),
            sql_timestamp(stages["preparing_at"]),
            sql_timestamp(stages["ready_at"]),
            sql_timestamp(stages["delivered_at"]),
        ),
    )


_SELECT = (
    "SELECT id, customer_key, customer_name, phone, delivery_address, order_lines,"
    "  subtotal_rm, delivery_fee_rm, total_rm,"
    "  placed_at, preparing_at, ready_at, delivered_at"
    " FROM food_orders"
)


def orders(limit: int = DEFAULT_LIMIT, now: datetime | None = None) -> list[Order]:
    """The back office, newest first."""
    rows = store.query(
        _SELECT + " ORDER BY placed_at DESC, id DESC LIMIT %s",
        (max(1, min(limit, MAX_LIMIT)),),
    )
    return [_order(row, now) for row in rows]


def orders_for(customer_key: str, limit: int = 3, now: datetime | None = None) -> list[Order]:
    """This customer's most recent orders, newest first."""
    rows = store.query(
        _SELECT + " WHERE customer_key = %s ORDER BY placed_at DESC, id DESC LIMIT %s",
        (customer_key, limit),
    )
    return [_order(row, now) for row in rows]


def _order(row: dict, now: datetime | None) -> Order:
    lines = row["order_lines"]
    if isinstance(lines, (str, bytes)):
        # PyMySQL hands a JSON column back as text.
        lines = json.loads(lines)
    return Order(
        id=row["id"],
        order_no=order_no(row["id"]),
        customer_key=row["customer_key"],
        customer_name=row["customer_name"],
        phone=row["phone"],
        delivery_address=row["delivery_address"],
        lines=[OrderLine(**line) for line in lines],
        subtotal_rm=float(row["subtotal_rm"]),
        delivery_fee_rm=float(row["delivery_fee_rm"]),
        total_rm=float(row["total_rm"]),
        # Local and naive on both sides: the row was stamped by this container's
        # clock (`sql_timestamp`), and this reads the same clock.
        status=status_at(row, now or datetime.now()),
        placed_at=_text(row["placed_at"]),
        preparing_at=_text(row["preparing_at"]),
        ready_at=_text(row["ready_at"]),
        delivered_at=_text(row["delivered_at"]),
    )


def _text(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds")


def minutes_until(moment: str, now: datetime | None = None) -> int:
    """Whole minutes from `now` to a timestamp this module produced, never below 0."""
    target = datetime.fromisoformat(moment)
    remaining = (target - (now or datetime.now())) / timedelta(minutes=1)
    return max(0, round(remaining))
