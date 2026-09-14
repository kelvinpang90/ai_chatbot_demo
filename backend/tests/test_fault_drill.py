"""The failure drill (task 27.1): break the next ERP call on purpose.

"What happens when it breaks?" is the question every owner thinks and few ask.
The drill answers it on cue: the operator arms it, the next ERP call fails the
way an unreachable back office fails, and the bot has to say so and hand over
instead of crashing or making a number up.

What is under test here is that the failure is the real one -- it arrives as the
same `ApiClientError` a dead host produces, so every ERP tool takes its own
tested failure path -- and that it happens exactly once.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.console import events
from app.main import app
from app.services import api_client, erp_client
from app.services.api_client import ApiClientError
from app.tools import erp

TOKEN = "s3cret-console-token"
HEADERS = {"X-Console-Token": TOKEN}


@pytest.fixture(autouse=True)
def drill_disarmed():
    """Process-global, like the tools switch: a test that arms it must disarm it,
    or the first ERP call of whichever test runs next fails for no visible reason."""
    erp_client.set_fault_drill(False)
    events.clear()
    try:
        yield
    finally:
        erp_client.set_fault_drill(False)
        events.clear()


@pytest.fixture
def client():
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            yield http


def _arm(client: TestClient, armed: bool):
    return client.post("/console/fault-drill", json={"armed": armed}, headers=HEADERS)


def test_the_drill_is_disarmed_until_someone_arms_it(client):
    response = client.get("/console/fault-drill", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"armed": False}


def test_arming_it_is_what_the_console_reads_back(client):
    assert _arm(client, True).json() == {"armed": True}
    assert client.get("/console/fault-drill", headers=HEADERS).json() == {"armed": True}
    assert _arm(client, False).json() == {"armed": False}


def test_the_next_erp_call_fails_as_an_unreachable_back_office_and_only_that_one():
    erp_client.set_fault_drill(True)

    with patch.object(api_client.JsonApiClient, "_request", return_value={"ok": 1}) as sent:
        with pytest.raises(ApiClientError) as failed:
            erp_client.client().post("/api/sales-orders", json={})
        # Never reached the ERP, so a write cannot have landed -- the tool tells
        # the customer "not placed" rather than "being checked".
        assert failed.value.may_have_landed is False
        assert not sent.called
        assert erp_client.fault_drill_armed() is False

        assert erp_client.client().get("/api/skus") == {"ok": 1}
        assert sent.called


def test_an_erp_tool_under_the_drill_gives_the_bot_its_ordinary_outage_answer():
    erp_client.set_fault_drill(True)

    with patch.object(api_client.httpx, "get") as get, patch.object(api_client.httpx, "post") as post:
        assert erp.erp_search_sku("earbuds") == erp.UNAVAILABLE

    assert not get.called and not post.called


def test_the_outage_answer_tells_the_bot_to_hand_over_rather_than_guess():
    """The drill's acceptance is "and then the takeover runs", which only happens
    if the answer the tool gives points the model at the tool that starts one --
    and the one bot on the ERP carries that tool."""
    assert "request_human_help" in erp.UNAVAILABLE
    assert "request_human_help" in get_bot("retail").tools


def test_the_console_feed_shows_arming_firing_and_disarming(client):
    _arm(client, True)
    with patch.object(api_client.JsonApiClient, "_request"):
        with pytest.raises(ApiClientError):
            erp_client.client().get("/api/skus")
    _arm(client, True)
    _arm(client, False)

    assert [(e.type, e.status) for e in events.since(0)] == [
        (events.FAULT_DRILL, "armed"),
        (events.FAULT_DRILL, "fired"),
        (events.FAULT_DRILL, "armed"),
        (events.FAULT_DRILL, "disarmed"),
    ]


def test_re_asserting_the_same_position_is_not_an_event(client):
    _arm(client, True)
    events.clear()

    _arm(client, True)

    assert events.since(0) == []


def test_the_drill_is_behind_the_console_token(client):
    assert client.post("/console/fault-drill", json={"armed": True}).status_code == 401
    assert client.get("/console/fault-drill").status_code == 401
    assert erp_client.fault_drill_armed() is False
