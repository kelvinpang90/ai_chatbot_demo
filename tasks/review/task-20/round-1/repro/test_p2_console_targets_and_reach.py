"""P2-1, P2-3 and P2-4: who the console can reach, and who can reach it.

P2-1 `waiting()` sorts oldest first, so the console's default target is
     whichever conversation nobody handed back last week.
P2-3 a customer who hides their number can be silenced but never answered.
P2-4 the console token, which by design sits in the nginx access log, is
     accepted from the query string on endpoints that write to a phone.
"""
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import handover, notify
from app.services.user_store import user_store

client = TestClient(app)
TOKEN = "console-token-for-repro"


@pytest.fixture
def _token():
    with patch("app.routers.console.settings.console_token", TOKEN):
        yield


def _held(phone: str, name: str | None = None):
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    profile.display_name = name
    user_store.save(profile)
    handover.begin(user_store.get(phone))


def test_p2_1_the_console_default_is_the_newest_handover():
    _held("60129990201", "Last week")
    time.sleep(0.02)
    _held("60129990202", "Today")

    assert handover.waiting()[0]["key_id"] == "60129990202"


def test_p2_3_a_customer_with_no_phone_number_can_still_be_answered(_token):
    hidden = "US.1349120865"
    _held(hidden)

    with patch.object(notify, "send_now"):
        response = client.post(
            "/console/reply",
            json={"key_id": hidden, "text": "Boss, we can do that."},
            headers={"X-Console-Token": TOKEN},
        )

    assert response.status_code == 200, response.json()


@pytest.mark.parametrize(
    "path,body",
    [
        ("/console/reply", {"key_id": "60129990204", "text": "hello"}),
        ("/console/handover", {"key_id": "60129990204", "active": True}),
    ],
)
def test_p2_4_a_token_in_the_url_cannot_write(_token, path, body):
    _held("60129990204")

    response = client.post(f"{path}?token={TOKEN}", json=body)

    assert response.status_code == 401, "a log-visible token wrote to a customer's phone"
