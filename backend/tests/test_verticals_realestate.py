"""KL Homes Realty's back office (task 23).

Driven against an in-memory stand-in for the store rather than a fake DB-API
connection: `test_verticals_db.py` already asserts that the store puts the SQL
and the parameters on the wire as written, and repeating that here would be
testing PyMySQL twice while testing the booking once. What these check is what
sits above the SQL -- that a booking comes back the way the screen will show it,
that a database which is down cannot pretend the back office is empty, and that
nobody can read a customer's phone number without the console token.

The one thing this cannot check is whether MySQL accepts the DDL; that is the
live run recorded in tasks/todo.md.
"""
from datetime import date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.verticals.db import StoreUnavailable
from app.verticals.realestate import models

TOKEN = "s3cret-console-token"

BOOKING = {
    "listing_id": "PROP-203",
    "customer_name": "陈家明 O'Brien",
    "phone": "+60123456789",
    "viewing_date": "2026-09-20",
    "preferred_time": "下午 3 点",
}


class FakeStore:
    """Enough of a database to answer the statements this module writes.

    Hand-rolled rather than sqlite, because the SQL is MySQL's (`ON DUPLICATE KEY
    UPDATE`, `DATETIME(3)`) and a dialect translation layer in a test is a second
    thing to get wrong. It dispatches on the leading verb and the table name,
    which is all the statements here differ by.
    """

    def __init__(self, fails: bool = False):
        self.listings: dict[str, tuple] = {}
        self.viewings: list[dict] = []
        self.fails = fails
        self.statements: list[str] = []

    def _guard(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))
        if self.fails:
            raise StoreUnavailable("the verticals database is unreachable")

    def execute(self, sql: str, params: tuple = ()) -> int:
        self._guard(sql)
        if "realestate_listings" in sql:
            self.listings[params[0]] = params
            return 0
        row = {
            "id": len(self.viewings) + 1,
            "listing_id": params[0],
            "customer_name": params[1],
            "phone": params[2],
            "viewing_date": date.fromisoformat(params[3]),
            "preferred_time": params[4],
            "created_at": datetime.strptime(params[5], "%Y-%m-%d %H:%M:%S.%f"),
        }
        self.viewings.append(row)
        return row["id"]

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        self._guard(sql)
        if "FROM realestate_listings" in sql:
            rows = [self._listing(row) for row in self.listings.values()]
            if "WHERE listing_id" in sql:
                return [row for row in rows if row["listing_id"] == params[0]]
            return sorted(rows, key=lambda row: row["price_rm"])
        rows = [self._joined(row) for row in self.viewings]
        if "WHERE v.id" in sql:
            return [row for row in rows if row["id"] == params[0]]
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return rows[: params[0]]

    def _listing(self, params: tuple) -> dict:
        keys = (
            "listing_id",
            "property_type",
            "area",
            "size_sqft",
            "bedrooms",
            "price_rm",
            "status",
        )
        return dict(zip(keys, params))

    def _joined(self, row: dict) -> dict:
        listing = self.listings.get(row["listing_id"])
        extra = self._listing(listing) if listing else {}
        return {
            **row,
            "area": extra.get("area"),
            "property_type": extra.get("property_type"),
            "price_rm": extra.get("price_rm"),
        }


@pytest.fixture
def fake_store():
    store = FakeStore()
    models.reset()
    with patch.object(models, "store", store):
        yield store
    models.reset()


@pytest.fixture
def dead_store():
    store = FakeStore(fails=True)
    models.reset()
    with patch.object(models, "store", store):
        yield store
    models.reset()


@pytest.fixture
def client(fake_store):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            yield http


def _post(client, **overrides):
    return client.post(
        "/api/verticals/realestate/viewings",
        json={**BOOKING, **overrides},
        headers={"X-Console-Token": TOKEN},
    )


def _get(client, path="/viewings", **params):
    return client.get(
        f"/api/verticals/realestate{path}",
        params=params,
        headers={"X-Console-Token": TOKEN},
    )


# --- the listings come from the bot, not from a second copy --------------------


def test_the_listings_are_the_ones_in_the_bots_prompt(fake_store):
    """The demo this breaks is the one where the bot quotes RM 620k and the back
    office on the next screen says something else."""
    from app.bots import registry as bots

    seeded = {listing.listing_id: listing for listing in models.listings()}
    for listing in bots.get_bot("realestate").context_data["listings"]:
        assert seeded[listing["listing_id"]].price_rm == listing["price_rm"]
        assert seeded[listing["listing_id"]].area == listing["area"]
        assert seeded[listing["listing_id"]].status == listing["status"]


def test_the_listings_are_seeded_once_not_per_request(fake_store):
    models.listings()
    before = len([s for s in fake_store.statements if s.startswith("INSERT INTO realestate_listings")])
    models.listings()
    after = len([s for s in fake_store.statements if s.startswith("INSERT INTO realestate_listings")])
    assert before == after == len(fake_store.listings)


def test_a_seed_that_could_not_finish_is_tried_again(dead_store):
    """Otherwise one restart while MySQL is down leaves the back office empty for
    the life of the process, behind a flag saying it was filled."""
    with pytest.raises(StoreUnavailable):
        models.listings()

    dead_store.fails = False
    assert len(models.listings()) == 8


def test_a_database_that_comes_back_empty_is_seeded_again(fake_store):
    """The hazard that pairs with a per-process flag: a replaced volume, a
    `docker compose down -v`, a dropped table. `db.py` recreates the schema, and
    a flag still saying "already seeded" would leave the back office blank and
    every booking 404-ing against ids the bot is still quoting."""
    assert len(models.listings()) == 8

    fake_store.fails = True
    with pytest.raises(StoreUnavailable):
        models.listings()
    fake_store.listings.clear()
    fake_store.fails = False

    assert len(models.listings()) == 8


def test_a_price_edited_in_the_bots_json_reaches_the_table(fake_store):
    """An upsert, not an insert-if-missing: the seed has to be able to correct a
    row that is already there."""
    models.listings()
    assert any(sql.startswith("INSERT INTO realestate_listings") and "ON DUPLICATE KEY UPDATE" in sql
               for sql in fake_store.statements)


# --- booking ------------------------------------------------------------------


def test_a_booking_comes_back_the_way_the_screen_will_show_it(client):
    response = _post(client)

    assert response.status_code == 201
    booked = response.json()
    assert booked["customer_name"] == "陈家明 O'Brien"
    assert booked["viewing_date"] == "2026-09-20"
    assert booked["preferred_time"] == "下午 3 点"
    # Joined from the listing, so the row reads as a property and not as an id.
    assert booked["area"] == "Petaling Jaya"
    assert booked["property_type"] == "Terrace House"


def test_a_booking_appears_in_the_back_office(client):
    """The acceptance for this task, in one test: curl it in, read it back."""
    _post(client)

    rows = _get(client).json()
    assert [row["customer_name"] for row in rows] == ["陈家明 O'Brien"]
    assert rows[0]["listing_id"] == "PROP-203"


def test_the_newest_booking_is_at_the_top(client):
    for name in ("first", "second", "third"):
        _post(client, customer_name=name)

    assert [row["customer_name"] for row in _get(client).json()] == ["third", "second", "first"]


def test_a_typo_in_the_listing_id_is_refused_rather_than_filed(client):
    """A row with a blank property beside it is worse on a screen than a 404 is
    in a terminal."""
    response = _post(client, listing_id="PROP-999")

    assert response.status_code == 404
    assert _get(client).json() == []


def test_a_booking_with_no_name_is_refused(client):
    assert _post(client, customer_name="").status_code == 422


def test_a_booking_with_no_date_is_refused(client):
    response = client.post(
        "/api/verticals/realestate/viewings",
        json={"listing_id": "PROP-203", "customer_name": "Ali"},
        headers={"X-Console-Token": TOKEN},
    )
    assert response.status_code == 422


def test_the_phone_and_the_time_are_optional(client):
    """WhatsApp already knows the number; the web chat line never will."""
    response = client.post(
        "/api/verticals/realestate/viewings",
        json={
            "listing_id": "PROP-203",
            "customer_name": "Ali",
            "viewing_date": "2026-09-20",
        },
        headers={"X-Console-Token": TOKEN},
    )

    assert response.status_code == 201
    assert response.json()["phone"] == ""
    assert response.json()["preferred_time"] == ""


def test_the_booking_is_stamped_by_this_container_not_by_mysql(fake_store):
    """`tasks/erp-crm-timezone.md` is eight hours of two other back offices
    explaining why the clock has to be the one in the compose file."""
    with patch("app.verticals.realestate.models.sql_timestamp", return_value="2026-09-20 15:04:05.123"):
        models.book_viewing(models.ViewingRequest(**BOOKING))

    assert fake_store.viewings[0]["created_at"] == datetime(2026, 9, 20, 15, 4, 5, 123000)


def test_the_timestamp_goes_out_without_an_offset_for_the_page_to_slice(client):
    """Not an ISO string with a `Z` on it, and not one without: `new Date()` on a
    naive string reads it as local time. The page slices this rather than parsing
    it, which is the other half of the same decision."""
    created = _post(client).json()["created_at"]

    assert created[4] == "-" and created[10] == " "
    assert "Z" not in created and "+" not in created


# --- a database that is down may not look like an empty back office -----------


def test_a_store_that_is_down_answers_503_not_an_empty_list(dead_store):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            response = http.get(
                "/api/verticals/realestate/viewings", headers={"X-Console-Token": TOKEN}
            )

    assert response.status_code == 503


def test_a_booking_that_could_not_be_written_says_so(dead_store):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            response = http.post(
                "/api/verticals/realestate/viewings",
                json=BOOKING,
                headers={"X-Console-Token": TOKEN},
            )

    assert response.status_code == 503


# --- the token ----------------------------------------------------------------


def test_the_back_office_is_closed_without_the_token(client):
    assert client.get("/api/verticals/realestate/viewings").status_code == 401
    assert client.post("/api/verticals/realestate/viewings", json=BOOKING).status_code == 401
    assert client.get("/api/verticals/realestate/listings").status_code == 401


def test_a_token_in_the_query_string_is_not_enough(client):
    """Header only, like every other console write since task 20: a query string
    lands in the proxy's access log and in browser history, and this list is
    names and phone numbers."""
    assert client.get("/api/verticals/realestate/viewings", params={"token": TOKEN}).status_code == 401


def test_an_unconfigured_console_closes_the_back_office_too(fake_store):
    with patch.object(settings, "console_token", ""):
        with TestClient(app) as http:
            response = http.get(
                "/api/verticals/realestate/viewings", headers={"X-Console-Token": "anything"}
            )

    assert response.status_code == 503
