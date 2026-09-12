"""The property agency's two tables, and everything that reads or writes them.

Models and queries in one module because there is no ORM to separate them into
(see the note in `verticals/db.py`): a `CREATE TABLE`, the shape it comes back
as, and the four statements that touch it are one thing to read, and splitting
them would mean opening two files to answer any question about either.

**The listings are seeded from the bot's own prompt data, not typed out again.**
`bots/data/realestate.json` already carries the eight properties, and the persona
above them says "Only the listings in front of you exist, with the id, price,
size and status they carry". A second copy in here would be free to disagree --
and the demo that breaks is the one where the bot quotes RM 620k and the back
office on the next screen says RM 650k.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from functools import wraps

from pydantic import BaseModel, Field

from app.bots import registry as bots
from app.services.clock import sql_timestamp
from app.verticals.db import StoreUnavailable, store

logger = logging.getLogger(__name__)

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS realestate_listings (
        listing_id VARCHAR(32) NOT NULL,
        property_type VARCHAR(64) NOT NULL,
        area VARCHAR(128) NOT NULL,
        size_sqft INT UNSIGNED NOT NULL,
        bedrooms TINYINT UNSIGNED NOT NULL,
        -- Money in DECIMAL, not FLOAT: nothing here is worth RM 849,999.99998.
        price_rm DECIMAL(12,2) NOT NULL,
        status VARCHAR(32) NOT NULL,
        PRIMARY KEY (listing_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS realestate_viewings (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        listing_id VARCHAR(32) NOT NULL,
        customer_name VARCHAR(128) NOT NULL,
        -- Blank is allowed: on WhatsApp we know the number already, and on the
        -- web chat line there is no number to know.
        phone VARCHAR(32) NOT NULL DEFAULT '',
        -- A DATE, because a date is what the client picks. Storing 00:00 beside
        -- it would put a time on the screen that nobody ever said.
        viewing_date DATE NOT NULL,
        -- Free text ("3pm", "petang", "after work"), because the form that fills
        -- it in is a WhatsApp Flow and its slot list is Meta's to change.
        preferred_time VARCHAR(32) NOT NULL DEFAULT '',
        created_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id),
        -- The back office is a list in the order things came in, and that is the
        -- only order anything reads this table in.
        KEY idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
)

# A page of the back office. Nothing here is paged through -- a demo books two
# or three viewings -- but an unbounded SELECT on a table that has been running
# since March is a screen that takes a second to draw for no reason.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class Listing(BaseModel):
    listing_id: str
    property_type: str
    area: str
    size_sqft: int
    bedrooms: int
    price_rm: float
    status: str


class ViewingRequest(BaseModel):
    """What the client filled in. Task 24's Flow form, or a curl."""

    listing_id: str = Field(min_length=1, max_length=32)
    customer_name: str = Field(min_length=1, max_length=128)
    viewing_date: date
    phone: str = Field(default="", max_length=32)
    preferred_time: str = Field(default="", max_length=32)


class Viewing(BaseModel):
    """One row of the back office, with enough of the listing to read it.

    The property columns come from a LEFT JOIN and are nullable for the reason
    the join is LEFT: a viewing whose listing was withdrawn is still a person
    expecting to be let into a building on Saturday, and dropping the row would
    be the worst possible way to say so.
    """

    id: int
    listing_id: str
    customer_name: str
    phone: str
    viewing_date: str
    preferred_time: str
    created_at: str
    area: str | None = None
    property_type: str | None = None
    price_rm: float | None = None


store.register(*SCHEMA)

_seed_lock = threading.Lock()
_seeded = False

_UPSERT_LISTING = (
    "INSERT INTO realestate_listings"
    " (listing_id, property_type, area, size_sqft, bedrooms, price_rm, status)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s)"
    # An upsert rather than an insert-if-missing, so editing a price in the bot's
    # JSON reaches the back office on the next restart instead of only ever
    # applying to a database nobody has run yet.
    " ON DUPLICATE KEY UPDATE property_type=VALUES(property_type), area=VALUES(area),"
    " size_sqft=VALUES(size_sqft), bedrooms=VALUES(bedrooms), price_rm=VALUES(price_rm),"
    " status=VALUES(status)"
)


def seed_listings() -> None:
    """Put the bot's eight properties in the table, once per process.

    Lazy rather than at import time, because importing this module must not
    depend on a database being up: the app has to start, and answer /health,
    with the verticals store unreachable.

    `_seeded` is only set once every row is in, so a store that was down when the
    first request arrived is tried again on the next one rather than leaving the
    back office permanently empty behind a flag that says it was filled.
    """
    global _seeded
    with _seed_lock:
        if _seeded:
            return
        for listing in _listings_from_the_bot():
            store.execute(
                _UPSERT_LISTING,
                (
                    listing["listing_id"],
                    listing["type"],
                    listing["area"],
                    listing["size_sqft"],
                    listing["bedrooms"],
                    listing["price_rm"],
                    listing["status"],
                ),
            )
        _seeded = True


def _reseed_if_the_store_went_away(call):
    """Forget that the listings were seeded, whenever a call finds the store gone.

    `_seeded` is per process, which is what makes an edited price in the bot's
    JSON reach the table on the next restart. The hazard that pairs with it is a
    database that comes back *empty* -- a replaced volume, a `docker compose down
    -v`, a dropped table -- because `db.py` will dutifully recreate the schema
    and this flag would then say the eight listings are already in it. The back
    office would be blank, and every booking would 404 against a listing id the
    bot is still quoting, for as long as the process lived.

    Any such loss shows up as a `StoreUnavailable` first: the connection to the
    old database dies, or the SELECT hits a table that is no longer there. So
    that is where the flag is dropped.
    """

    @wraps(call)
    def guarded(*args, **kwargs):
        global _seeded
        try:
            return call(*args, **kwargs)
        except StoreUnavailable:
            _seeded = False
            raise

    return guarded


def _listings_from_the_bot() -> list[dict]:
    bot = bots.get_bot("realestate")
    if bot is None:
        # Only reachable if the JSON was deleted or renamed, which the bot list
        # would notice long before this does. Said out loud rather than raising:
        # an empty listings table is a back office with nothing in it, and a
        # crash here would take the whole vertical down with it.
        logger.warning("no realestate bot config, so there are no listings to seed")
        return []
    return list(bot.context_data.get("listings", []))


@_reseed_if_the_store_went_away
def listings() -> list[Listing]:
    seed_listings()
    rows = store.query(
        "SELECT listing_id, property_type, area, size_sqft, bedrooms, price_rm, status"
        " FROM realestate_listings ORDER BY price_rm"
    )
    return [Listing(**row) for row in rows]


@_reseed_if_the_store_went_away
def listing_exists(listing_id: str) -> bool:
    seed_listings()
    return bool(
        store.query(
            "SELECT listing_id FROM realestate_listings WHERE listing_id = %s",
            (listing_id,),
        )
    )


@_reseed_if_the_store_went_away
def book_viewing(request: ViewingRequest, at: float | None = None) -> int:
    """File a viewing request; returns its id."""
    return store.execute(
        "INSERT INTO realestate_viewings"
        " (listing_id, customer_name, phone, viewing_date, preferred_time, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (
            request.listing_id,
            request.customer_name.strip(),
            request.phone.strip(),
            request.viewing_date.isoformat(),
            request.preferred_time.strip(),
            sql_timestamp(at),
        ),
    )


_SELECT_VIEWINGS = (
    "SELECT v.id, v.listing_id, v.customer_name, v.phone, v.viewing_date,"
    "  v.preferred_time, v.created_at,"
    "  l.area, l.property_type, l.price_rm"
    " FROM realestate_viewings v"
    " LEFT JOIN realestate_listings l ON l.listing_id = v.listing_id"
)


@_reseed_if_the_store_went_away
def viewings(limit: int = DEFAULT_LIMIT) -> list[Viewing]:
    """The back office, newest first."""
    rows = store.query(
        # By id as well as by time, because DATETIME(3) is not enough resolution
        # to separate two bookings written in the same millisecond -- which is
        # what "three people in a room" looks like from in here.
        _SELECT_VIEWINGS + " ORDER BY v.created_at DESC, v.id DESC LIMIT %s",
        (max(1, min(limit, MAX_LIMIT)),),
    )
    return [_viewing(row) for row in rows]


@_reseed_if_the_store_went_away
def get_viewing(viewing_id: int) -> Viewing | None:
    rows = store.query(_SELECT_VIEWINGS + " WHERE v.id = %s", (viewing_id,))
    return _viewing(rows[0]) if rows else None


def _viewing(row: dict) -> Viewing:
    return Viewing(
        id=row["id"],
        listing_id=row["listing_id"],
        customer_name=row["customer_name"],
        phone=row["phone"],
        viewing_date=_text(row["viewing_date"]),
        preferred_time=row["preferred_time"],
        created_at=_text(row["created_at"]),
        area=row["area"],
        property_type=row["property_type"],
        price_rm=None if row["price_rm"] is None else float(row["price_rm"]),
    )


def _text(value) -> str:
    """A date or datetime out of MySQL, as the string the screen shows.

    Spelled without a timezone offset on purpose, and read by a page that slices
    it rather than parsing it. `tasks/erp-crm-timezone.md` is eight hours of two
    other back offices explaining why: a naive timestamp handed to `new Date()`
    is read as local time, and the number printed is whatever the database
    happened to store.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="milliseconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def reset() -> None:
    """Forget that the listings were seeded. Tests."""
    global _seeded
    with _seed_lock:
        _seeded = False
