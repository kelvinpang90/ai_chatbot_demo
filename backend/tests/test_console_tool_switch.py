"""The control arm: one switch that detaches every bot's tools at once.

What it is for is the demo, not the product. The same bot, asked the same
question twice, answers once from the ERP and once from the JSON in its prompt --
and the second answer sounds exactly as confident as the first. That is the whole
argument of this batch, and this switch is what lets a customer watch it happen
instead of being told about it.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.console import events
from app.main import app
from app.tools import registry as tool_registry

TOKEN = "s3cret-console-token"


@pytest.fixture(autouse=True)
def tools_back_on():
    """The flag is process-global, so a test that throws it must put it back.

    Left off, it would empty `get_tools` for every test that runs after this
    file -- a whole suite quietly asserting against the control arm.
    """
    try:
        yield
    finally:
        tool_registry.set_tools_enabled(True)


@pytest.fixture(autouse=True)
def clean_buffer():
    events.clear()
    yield
    events.clear()


@pytest.fixture
def client():
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            yield http


def _flip(client: TestClient, enabled: bool):
    return client.post(
        "/console/tools", json={"enabled": enabled}, headers={"X-Console-Token": TOKEN}
    )


def test_tools_are_attached_until_someone_says_otherwise(client):
    response = client.get("/console/tools", headers={"X-Console-Token": TOKEN})

    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert tool_registry.get_tools("retail")


def test_switching_off_empties_every_bot_and_switching_back_restores_it(client):
    assert _flip(client, False).json() == {"enabled": False}

    # Not "retail has fewer tools": none of them has any, which is what puts the
    # bot on the no-tools path it has had since task 2.
    assert tool_registry.get_tools("retail") == []
    assert tool_registry.get_tools("hotel") == []
    assert client.get("/console/tools", headers={"X-Console-Token": TOKEN}).json() == {
        "enabled": False
    }

    assert _flip(client, True).json() == {"enabled": True}
    assert tool_registry.get_tools("retail")


def test_the_console_feed_shows_the_switch_being_thrown(client):
    _flip(client, False)
    _flip(client, True)

    assert [(e.type, e.status) for e in events.since(0)] == [
        (events.TOOLS_SWITCHED, "off"),
        (events.TOOLS_SWITCHED, "on"),
    ]


def test_re_asserting_the_same_position_is_not_an_event(client):
    """A second screen syncing itself is not the operator doing something."""
    _flip(client, False)
    events.clear()

    _flip(client, False)

    assert events.since(0) == []


def test_the_switch_is_behind_the_console_token(client):
    assert client.post("/console/tools", json={"enabled": False}).status_code == 401
    assert client.get("/console/tools").status_code == 401
    # The refused request changed nothing.
    assert tool_registry.get_tools("retail")
