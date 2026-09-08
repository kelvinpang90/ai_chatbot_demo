"""Reading the audit log back, and the token that now stands in front of it.

The rows here are handed in as fake query results rather than written first: what
these tests are for is the shape of the answer and the guard on the door. That
the SQL itself runs is settled by the live MySQL run recorded in tasks/todo.md.
"""
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import console
from app.services.user_store import UserProfile

TOKEN = "s3cret-console-token"


@pytest.fixture
def client():
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            yield http


@pytest.fixture
def rows():
    """Answer each query in turn, in the order the router asks them."""
    answers: list[list[dict]] = []

    def query(sql, params=()):
        return answers.pop(0) if answers else []

    with patch.object(console.audit_store, "query", side_effect=query):
        yield answers


def _when(day=8, hour=13, minute=30, second=0, ms=0):
    return datetime(2026, 9, day, hour, minute, second, ms * 1000)


# --- the door ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/console/stream", "/console/history", "/console/history/c-1"])
def test_no_token_no_console(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/console/stream", "/console/history", "/console/history/c-1"])
def test_an_unconfigured_console_is_closed_not_open(path):
    """The opposite of how the chat side reads an empty password, deliberately.

    A deployment that forgets CONSOLE_TOKEN loses the console. If this defaulted
    open, it would instead publish every customer transcript the moment nginx
    started proxying /console/ -- which task 37.1 makes it do.
    """
    with patch.object(settings, "console_token", ""):
        with TestClient(app) as http:
            assert http.get(path).status_code == 503


def test_a_wrong_token_is_refused(client, rows):
    assert client.get("/console/history", headers={"X-Console-Token": "nope"}).status_code == 401


def test_the_token_may_travel_in_the_query_string(client, rows):
    """EventSource cannot set headers, so the live stream depends on this."""
    rows.append([])
    assert client.get(f"/console/history?token={TOKEN}").status_code == 200


def test_the_token_may_travel_in_a_header(client, rows):
    rows.append([])
    assert client.get("/console/history", headers={"X-Console-Token": TOKEN}).status_code == 200


# --- listing -----------------------------------------------------------------


def _summary_rows():
    return [
        {
            "conversation_id": "c-1",
            "key_id": "60173948123",
            "channel": "whatsapp",
            "bot_id": "retail",
            "messages": 6,
            "started_at": _when(minute=30),
            "last_at": _when(minute=44, ms=938),
        }
    ]


def test_a_conversation_carries_its_counts_and_its_bill(client, rows):
    rows.append(_summary_rows())
    rows.append([{"conversation_id": "c-1", "n": 3}])
    rows.append(
        [
            {
                "conversation_id": "c-1",
                "input_tokens": 12000,
                "output_tokens": 300,
                "api_turns": 4,
            }
        ]
    )

    body = client.get("/console/history", headers={"X-Console-Token": TOKEN}).json()
    got = body["conversations"][0]
    assert got["messages"] == 6
    assert got["tool_calls"] == 3
    assert (got["input_tokens"], got["output_tokens"], got["api_turns"]) == (12000, 300, 4)
    assert got["last_at"] == "2026-09-08 13:44:00.938"


def test_a_conversation_with_no_tools_and_no_usage_still_lists(client, rows):
    """A light bot has no tools, and a reply that failed before its first API
    call has no usage row. Neither is a reason to hide the conversation."""
    rows.append(_summary_rows())
    rows.append([])
    rows.append([])

    got = client.get("/console/history", headers={"X-Console-Token": TOKEN}).json()
    assert got["conversations"][0]["tool_calls"] == 0
    assert got["conversations"][0]["input_tokens"] == 0


def test_a_name_is_shown_where_the_profile_is_still_alive(client, rows):
    rows.append(_summary_rows())
    rows.append([])
    rows.append([])
    profile = UserProfile(key_id="60173948123", display_name="David Park")
    with patch.object(console.user_store, "get", return_value=profile):
        got = client.get("/console/history", headers={"X-Console-Token": TOKEN}).json()
    assert got["conversations"][0]["display_name"] == "David Park"


def test_an_expired_profile_costs_the_name_not_the_conversation(client, rows):
    """Profiles last seven days; transcripts do not expire. An older one shows a
    number, which is the honest answer rather than a missing row."""
    rows.append(_summary_rows())
    rows.append([])
    rows.append([])
    with patch.object(console.user_store, "get", return_value=None):
        got = client.get("/console/history", headers={"X-Console-Token": TOKEN}).json()
    assert got["conversations"][0]["display_name"] is None
    assert got["conversations"][0]["key_id"] == "60173948123"


def test_a_number_is_normalised_before_it_is_searched(client, rows):
    """The point of task 33's normalisation, applied to search: the national form
    a Malaysian actually types has to find the E.164 the webhook filed."""
    seen = []

    def query(sql, params=()):
        seen.append((sql, params))
        return []

    with patch.object(console.audit_store, "query", side_effect=query):
        client.get("/console/history?key=017-394 8123", headers={"X-Console-Token": TOKEN})
    assert "60173948123" in seen[0][1]


def test_an_unusable_number_matches_nothing_rather_than_everything(client, rows):
    got = client.get("/console/history?key=hello", headers={"X-Console-Token": TOKEN}).json()
    assert got["conversations"] == []


def test_the_page_size_is_capped(client, rows):
    seen = []

    def query(sql, params=()):
        seen.append(params)
        return []

    with patch.object(console.audit_store, "query", side_effect=query):
        client.get("/console/history?limit=99999", headers={"X-Console-Token": TOKEN})
    assert console.MAX_LIMIT in seen[0]


# --- one conversation --------------------------------------------------------


def test_a_transcript_hangs_each_tool_call_under_the_message_that_caused_it(client, rows):
    rows.append(
        [
            {
                "id": 1,
                "key_id": "60173948123",
                "channel": "whatsapp",
                "bot_id": "retail",
                "role": "user",
                "content": "ada stock?",
                "source": "voice",
                "created_at": _when(),
            },
            {
                "id": 2,
                "key_id": "60173948123",
                "channel": "whatsapp",
                "bot_id": "retail",
                "role": "assistant",
                "content": "47 in stock.",
                "source": "text",
                "created_at": _when(second=3),
            },
        ]
    )
    rows.append(
        [
            {
                "message_id": 1,
                "tool": "erp_search_sku",
                "tool_use_id": "tu_1",
                "input": '{"term": "earbuds"}',
                "output": "[...]",
                "duration_ms": 201,
                "status": "ok",
                "created_at": _when(second=1),
            }
        ]
    )
    rows.append([{"input_tokens": 12000, "output_tokens": 300, "cache_write_tokens": 1097,
                  "cache_read_tokens": 0, "api_turns": 4}])

    got = client.get("/console/history/c-1", headers={"X-Console-Token": TOKEN}).json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][0]["source"] == "voice"
    assert got["messages"][0]["tool_calls"][0]["tool"] == "erp_search_sku"
    # Parsed, so a page can render the arguments as fields rather than a blob.
    assert got["messages"][0]["tool_calls"][0]["input"] == {"term": "earbuds"}
    assert got["messages"][1]["tool_calls"] == []
    assert got["api_turns"] == 4


def test_a_json_column_already_parsed_by_the_driver_is_left_alone(client, rows):
    rows.append(
        [
            {
                "id": 1,
                "key_id": "60173948123",
                "channel": "web",
                "bot_id": "retail",
                "role": "user",
                "content": "hi",
                "source": "text",
                "created_at": _when(),
            }
        ]
    )
    rows.append(
        [
            {
                "message_id": 1,
                "tool": "t",
                "tool_use_id": "tu",
                "input": {"already": "parsed"},
                "output": None,
                "duration_ms": None,
                "status": "ok",
                "created_at": _when(),
            }
        ]
    )
    rows.append([])
    got = client.get("/console/history/c-1", headers={"X-Console-Token": TOKEN}).json()
    assert got["messages"][0]["tool_calls"][0]["input"] == {"already": "parsed"}


def test_an_unknown_conversation_is_a_404_not_an_empty_transcript(client, rows):
    rows.append([])
    assert client.get("/console/history/nope", headers={"X-Console-Token": TOKEN}).status_code == 404


def test_a_conversation_reads_back_with_the_log_switched_off(client):
    """MYSQL_URL unset: every query returns [], so the page says "not found"
    rather than raising at whoever opened it."""
    assert client.get("/console/history/c-1", headers={"X-Console-Token": TOKEN}).status_code == 404
    assert client.get("/console/history", headers={"X-Console-Token": TOKEN}).json()[
        "conversations"
    ] == []
