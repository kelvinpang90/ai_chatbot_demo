"""Langkawi Breeze Resort's back office (task 38.3): the list, behind the token.

The booking tools themselves are driven in `test_local_tools.py`. What these check
is the other end: that a booking the bot made shows up here with the guest it
belongs to, newest first, and that a database which is down answers 503 rather
than an empty list that would read as "no bookings yet" on a client's screen.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.main import app
from app.services.user_store import UserProfile
from app.tools import local
from app.verticals.hotel import models

TOKEN = "s3cret-console-token"
SOON = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=32)).isoformat()


def _book(phone: str, name: str, room: str = "Sea View Suite") -> dict:
    guest = UserProfile(key_id=phone, phone=phone, display_name=name)
    with local.serving(get_bot("hotel"), guest):
        return json.loads(local.hotel_create_booking(room, SOON, LATER, 2))


def _get(http, **headers):
    return http.get("/api/verticals/hotel/bookings", headers=headers)


def test_the_back_office_lists_every_guests_booking_newest_first(hotel_store):
    first = _book("60173948123", "Aisyah")
    second = _book("60129998888", "Tan Wei Ling", room="Beachfront Villa")

    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            rows = _get(http, **{"X-Console-Token": TOKEN}).json()

    assert [row["booking_id"] for row in rows] == [second["booking_id"], first["booking_id"]]
    newest = rows[0]
    assert newest["customer_name"] == "Tan Wei Ling"
    assert newest["phone"] == "60129998888"
    assert newest["room_type"] == "Beachfront Villa"
    assert (newest["check_in"], newest["check_out"], newest["nights"]) == (SOON, LATER, 2)
    assert newest["total_rm"] == 1900
    assert newest["status"] == models.CONFIRMED


def test_a_changed_booking_shows_its_new_stay_and_when_it_changed(hotel_store):
    guest = UserProfile(key_id="60173948123", phone="60173948123")
    with local.serving(get_bot("hotel"), guest):
        booking = json.loads(local.hotel_create_booking("Sea View Suite", SOON, LATER, 2))
        local.hotel_modify_booking(booking["booking_id"], room_type="Family Suite")

    (row,) = models.bookings()
    assert row.room_type == "Family Suite"
    assert row.total_rm == 960
    assert row.updated_at is not None


def test_a_back_office_that_is_down_answers_503_not_an_empty_list(hotel_store):
    hotel_store.fails = True
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http, **{"X-Console-Token": TOKEN}).status_code == 503


def test_the_back_office_is_closed_without_the_token_in_the_header(hotel_store):
    _book("60173948123", "Aisyah")
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http).status_code == 401
            assert http.get(f"/api/verticals/hotel/bookings?token={TOKEN}").status_code == 401


def test_a_booking_number_that_is_not_ours_points_at_nothing():
    assert models.row_id("BK-00012") == 12
    assert models.row_id(" bk-7 ") == 7
    assert models.row_id("FD-00012") is None
    assert models.row_id("12") is None
    assert models.row_id("") is None
