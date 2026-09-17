"""The SaaS support desk's back office (task 38.4): the list, behind the token.

The ticket tools themselves are driven in `test_local_tools.py`. What these check
is the other end: a ticket the bot opened shows up here with the customer it
belongs to, newest first, and a database that is down answers 503 rather than an
empty queue.
"""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.main import app
from app.services.user_store import UserProfile
from app.tools import local
from app.verticals.saas import models

TOKEN = "s3cret-console-token"


def _open(phone: str, name: str, subject: str, priority: str = "normal") -> dict:
    customer = UserProfile(key_id=phone, phone=phone, display_name=name)
    with local.serving(get_bot("saas"), customer):
        return json.loads(local.saas_create_ticket(subject, f"{subject}, reported.", priority))


def _get(http, **headers):
    return http.get("/api/verticals/saas/tickets", headers=headers)


def test_the_back_office_lists_every_customers_ticket_newest_first(saas_store):
    first = _open("60173948123", "Aisyah", "Export fails")
    second = _open("60129998888", "Tan Wei Ling", "Cannot log in", priority="urgent")

    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            rows = _get(http, **{"X-Console-Token": TOKEN}).json()

    assert [row["ticket_id"] for row in rows] == [second["ticket_id"], first["ticket_id"]]
    newest = rows[0]
    assert (newest["customer_name"], newest["phone"]) == ("Tan Wei Ling", "60129998888")
    assert (newest["subject"], newest["priority"]) == ("Cannot log in", "urgent")
    assert newest["description"] == "Cannot log in, reported."
    assert newest["status"] == models.OPEN


def test_a_back_office_that_is_down_answers_503_not_an_empty_list(saas_store):
    saas_store.fails = True
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http, **{"X-Console-Token": TOKEN}).status_code == 503


def test_the_back_office_is_closed_without_the_token_in_the_header(saas_store):
    _open("60173948123", "Aisyah", "Export fails")
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http).status_code == 401
            assert http.get(f"/api/verticals/saas/tickets?token={TOKEN}").status_code == 401


def test_a_ticket_number_that_is_not_ours_points_at_nothing():
    assert models.row_id("TCK-00012") == 12
    assert models.row_id(" tck-7 ") == 7
    assert models.row_id("BK-00012") is None
    assert models.row_id("12") is None
    assert models.row_id("") is None
