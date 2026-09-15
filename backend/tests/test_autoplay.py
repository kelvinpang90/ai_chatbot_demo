"""Autoplay (task 29): the console plays scene 1 with nobody at the keyboard.

Only the customer's lines are scripted. Every line goes down the web chat's own
path -- the same `send_message` a visitor's browser calls -- so the model, the
tools, the ERP order and the CRM card are all real. What is under test here is
the part that is not the model: the lines go out in order, into a fresh retail
conversation, a line whose work is already done is skipped rather than said, and
the run can be stopped.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.console import autoplay, events
from app.main import app
from app.services import llm
from app.services.user_store import identity, user_store

TOKEN = "s3cret-console-token"
HEADERS = {"X-Console-Token": TOKEN}
KEY = identity(settings.autoplay_phone)


@pytest.fixture(autouse=True)
def quiet():
    """No pauses between lines, a clean feed, and no run left over."""
    events.clear()
    with patch.object(autoplay, "PAUSE_SECONDS", 0):
        yield
    autoplay.stop()
    autoplay.join()
    autoplay.reset()
    events.clear()


@pytest.fixture
def client():
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            yield http


def _replies(tools_by_turn: dict[int, str] | None = None):
    """A stand-in model: says something each turn, and on the turns named
    reports a tool as having succeeded the way the tool runner does."""
    tools_by_turn = tools_by_turn or {}
    turn = {"n": 0}

    def reply(bot, profile, history):
        turn["n"] += 1
        tool = tools_by_turn.get(turn["n"])
        if tool:
            events.emit(type=events.TOOL_END, tool=tool, output='{"order_no": "SO-1"}', status="ok")
        return f"reply {turn['n']}"

    return reply


def _said() -> list[str]:
    profile = user_store.get(KEY)
    return [m.content for m in profile.history if m.role == "user"]


def test_every_line_is_said_in_order_to_a_fresh_retail_conversation():
    user_store.get_or_create(KEY)
    with patch.object(llm, "get_reply", side_effect=_replies()):
        autoplay.play()

    profile = user_store.get(KEY)
    assert profile.bot_id == "retail"
    assert _said() == [step.say for step in autoplay.SCRIPT]
    state = autoplay.state()
    assert state.running is False and state.error is None
    assert state.step == state.total == len(autoplay.SCRIPT)


def test_the_run_opens_a_new_conversation_rather_than_continuing_an_old_one():
    with patch.object(llm, "get_reply", side_effect=_replies()):
        autoplay.play()
        first = user_store.get(KEY).conversation_id
        autoplay.play()

    assert user_store.get(KEY).conversation_id != first
    assert _said() == [step.say for step in autoplay.SCRIPT]


def test_a_line_whose_work_the_bot_already_did_is_skipped():
    """The bot often places the order as soon as it has the details, and then
    "yes, place it" would read as the customer not listening."""
    ordered_at = next(
        i for i, step in enumerate(autoplay.SCRIPT, 1) if step.unless_done == "erp_create_sales_order"
    )
    # The turn before the confirmation is where the order lands.
    with patch.object(llm, "get_reply", side_effect=_replies({ordered_at - 1: "erp_create_sales_order"})):
        autoplay.play()

    skipped = [s.say for s in autoplay.SCRIPT if s.unless_done == "erp_create_sales_order"]
    assert all(line not in _said() for line in skipped)
    assert autoplay.state().skipped == len(skipped)


def test_a_failed_tool_does_not_count_as_done():
    """A refusal or an outage is not an order, so the confirmation still goes."""
    def reply(bot, profile, history):
        events.emit(type=events.TOOL_END, tool="erp_create_sales_order", output="The order could not be created", status="ok")
        return "sorry"

    with patch.object(llm, "get_reply", side_effect=reply):
        autoplay.play()

    assert _said() == [step.say for step in autoplay.SCRIPT]


def test_another_customers_order_does_not_count_either():
    def reply(bot, profile, history):
        events.emit(type=events.TOOL_END, tool="erp_create_sales_order", output="{}", status="ok", key_id="60111111111")
        return "ok"

    with patch.object(llm, "get_reply", side_effect=reply):
        autoplay.play()

    assert _said() == [step.say for step in autoplay.SCRIPT]


def test_stopping_ends_the_run_before_the_next_line():
    def reply(bot, profile, history):
        autoplay.stop()
        return "ok"

    with patch.object(llm, "get_reply", side_effect=reply):
        autoplay.play()

    assert _said() == [autoplay.SCRIPT[0].say]
    state = autoplay.state()
    assert state.running is False and state.stopped is True


def test_a_turn_that_blows_up_ends_the_run_and_says_why():
    with patch.object(llm, "get_reply", side_effect=RuntimeError("model down")):
        autoplay.play()

    state = autoplay.state()
    assert state.running is False
    assert "model down" in state.error


def test_the_console_starts_it_and_reads_where_it_got_to(client):
    with patch.object(llm, "get_reply", side_effect=_replies()):
        started = client.post("/console/autoplay", json={"playing": True}, headers=HEADERS)
        assert started.status_code == 200
        autoplay.join()

    state = client.get("/console/autoplay", headers=HEADERS).json()
    assert state["running"] is False
    assert state["step"] == state["total"] == len(autoplay.SCRIPT)
    assert state["key_id"] == KEY


def test_a_second_start_while_one_is_running_is_refused(client):
    with patch.object(autoplay, "is_running", return_value=True):
        response = client.post("/console/autoplay", json={"playing": True}, headers=HEADERS)
    assert response.status_code == 409


def test_autoplay_is_behind_the_console_token(client):
    assert client.post("/console/autoplay", json={"playing": True}).status_code == 401
    assert client.get("/console/autoplay").status_code == 401
    assert user_store.get(KEY) is None
