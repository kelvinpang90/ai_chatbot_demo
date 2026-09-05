"""The web chat, opened as a phone number (task 33).

The web used to hand out an anonymous session id: a visitor was nobody, their
conversation lived in process memory, and `llm.get_reply` was called with no
customer at all. Now the first thing the page asks for is a phone number, and
from there the two channels are one path -- same `user_store` record, same
seven-day Redis key, same customer handed to the model.

The test that matters most is `test_a_conversation_from_the_phone_is_waiting_on
_the_laptop`: type the number a customer uses on WhatsApp and their conversation
is there. That is the demo this task exists for.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.whatsapp_webhook import dispatch_message
from app.services import llm
from app.services.user_store import user_store

@pytest.fixture
def client():
    """A web client. The access password was dropped on 2026-09-05, so there is
    nothing to log in to: the demo is open to whoever has the link."""
    with TestClient(app) as http:
        yield http


def _text_message(phone: str, text: str, seq: int = 1) -> dict:
    return {
        "id": f"wamid.{phone}.{seq}",
        "from": phone,
        "type": "text",
        "text": {"body": text},
    }


def _list_reply(phone: str, option_id: str) -> dict:
    return {
        "id": f"wamid.{phone}.pick",
        "from": phone,
        "type": "interactive",
        "interactive": {"type": "list_reply", "list_reply": {"id": option_id}},
    }


def _identify(client: TestClient, phone: str, lang: str = "en"):
    return client.post("/api/chat/identify", json={"phone": phone, "lang": lang})


# -- who is at the keyboard ---------------------------------------------------


def test_a_number_new_to_us_starts_at_the_demo_menu(client):
    response = _identify(client, "+60 12-999 0101")

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "60129990101"
    assert body["bot"] is None
    assert body["history"] == []


def test_looking_a_number_up_does_not_make_it_a_customer(client):
    """A wrong number typed into the box must leave nothing behind. Otherwise
    every typo becomes a record -- and from task 34 a row in the CRM."""
    _identify(client, "60129990102")

    assert user_store.get("60129990102") is None


@pytest.mark.parametrize("junk", ["", "   ", "hello", "call me at 7", "ext 4021"])
def test_something_that_is_not_a_number_is_refused(client, junk):
    """`identity` on its own would file "call me at 7" under "7", i.e. show one
    visitor another visitor's conversation."""
    assert _identify(client, junk).status_code == 400


def test_the_demo_asks_for_nothing_but_the_number():
    """No password, and no leftover login route to send anyone to. A 401 here
    would strand the page, which has no gate left to show."""
    with TestClient(app) as anyone:
        assert anyone.post("/api/chat/identify", json={"phone": "60129990103"}).status_code == 200
        assert anyone.get("/api/bots").status_code == 200
        assert anyone.post("/api/auth/login", json={"password": "x"}).status_code == 404


# -- the acceptance criterion -------------------------------------------------


def test_a_conversation_from_the_phone_is_waiting_on_the_laptop(client):
    """Task 33's acceptance test, and the demo it is for: a customer talks to the
    bot on WhatsApp, someone types that number on a laptop, and the conversation
    is there -- written the way a salesperson writes a number, not the way Meta
    sends one."""
    dispatch_message(_list_reply("60173948123", "retail"))
    with patch.object(llm, "get_reply", return_value="Yes bos, RM 328.90 each."):
        dispatch_message(_text_message("60173948123", "earbuds got stock ah?"))

    body = _identify(client, "+60 17-394 8123").json()

    assert body["bot"]["id"] == "retail"
    assert [(turn["role"], turn["content"]) for turn in body["history"]] == [
        ("user", "earbuds got stock ah?"),
        ("assistant", "Yes bos, RM 328.90 each."),
    ]


def test_the_number_typed_the_way_a_malaysian_writes_it_finds_them(client):
    """The same conversation, reached from "017-...", which is what someone
    standing at the laptop actually types. Filed on its digits alone it would be
    a different customer with nothing on file."""
    dispatch_message(_list_reply("60173948124", "retail"))
    with patch.object(llm, "get_reply", return_value="RM 328.90."):
        dispatch_message(_text_message("60173948124", "how much?"))

    body = _identify(client, "017-3948124").json()

    assert body["key"] == "60173948124"
    assert body["bot"]["id"] == "retail"
    assert [turn["content"] for turn in body["history"]] == ["how much?", "RM 328.90."]


def test_what_is_said_on_the_laptop_is_there_on_the_phone(client):
    """The same trade in the other direction, which is what "one path" means:
    the web is not a read-only window onto WhatsApp's record, it writes to it."""
    key = _identify(client, "60129990104").json()["key"]
    client.post(f"/api/chat/{key}/select", json={"bot_id": "retail", "lang": "en"})
    with patch.object(llm, "get_reply", return_value="We deliver Tuesday."):
        client.post(f"/api/chat/{key}/message", json={"message": "when can you deliver?"})

    seen = {}

    def capture(bot, customer, history):
        seen["history"] = [(m.role, m.content) for m in history]
        return "Tuesday, confirmed."

    with patch.object(llm, "get_reply", side_effect=capture):
        dispatch_message(_text_message("60129990104", "still Tuesday?"))

    assert seen["history"] == [
        ("user", "when can you deliver?"),
        ("assistant", "We deliver Tuesday."),
        ("user", "still Tuesday?"),
    ]


def test_the_model_is_handed_the_number_the_visitor_typed(client):
    """The web used to pass no customer at all, so the retail bot had nobody to
    look up in the CRM. It does now, and it is a real number."""
    key = _identify(client, "60129990105").json()["key"]
    client.post(f"/api/chat/{key}/select", json={"bot_id": "retail", "lang": "en"})
    seen = {}

    def capture(bot, customer, history):
        seen["customer"] = customer
        return "Sure."

    with patch.object(llm, "get_reply", side_effect=capture):
        client.post(f"/api/chat/{key}/message", json={"message": "hi"})

    assert seen["customer"] is not None
    assert seen["customer"].phone == "60129990105"


# -- the rest of the path -----------------------------------------------------


def test_picking_a_demo_files_the_choice_and_greets(client):
    key = _identify(client, "60129990106").json()["key"]

    response = client.post(f"/api/chat/{key}/select", json={"bot_id": "retail", "lang": "zh"})

    assert response.status_code == 200
    assert response.json()["greeting"]
    assert user_store.get(key).bot_id == "retail"


def test_a_demo_that_does_not_exist_is_a_404(client):
    key = _identify(client, "60129990107").json()["key"]
    assert client.post(f"/api/chat/{key}/select", json={"bot_id": "nope"}).status_code == 404


def test_talking_before_picking_a_demo_is_refused(client):
    key = _identify(client, "60129990108").json()["key"]

    response = client.post(f"/api/chat/{key}/message", json={"message": "hello"})

    assert response.status_code == 409


def test_a_key_nothing_can_be_filed_under_is_refused(client):
    """The key is normalised by /identify, but it comes back in a URL, so it is
    checked again rather than trusted."""
    assert client.post("/api/chat/abc/message", json={"message": "hi"}).status_code == 400
    assert client.post("/api/chat/abc/select", json={"bot_id": "retail"}).status_code == 400
    assert client.post("/api/chat/abc/reset").status_code == 400


def test_the_conversation_is_on_file_after_the_reply(client):
    key = _identify(client, "60129990109").json()["key"]
    client.post(f"/api/chat/{key}/select", json={"bot_id": "retail", "lang": "en"})

    with patch.object(llm, "get_reply", return_value="Three colours."):
        client.post(f"/api/chat/{key}/message", json={"message": "what colours?"})

    stored = user_store.get(key)
    assert [(m.role, m.content) for m in stored.history] == [
        ("user", "what colours?"),
        ("assistant", "Three colours."),
    ]


def test_restarting_clears_the_conversation_but_keeps_the_customer(client):
    """Same as WhatsApp's "menu": changing which demo you are showing is not the
    same as forgetting who the customer is."""
    key = _identify(client, "60129990110").json()["key"]
    client.post(f"/api/chat/{key}/select", json={"bot_id": "retail", "lang": "en"})
    with patch.object(llm, "get_reply", return_value="Noted."):
        client.post(f"/api/chat/{key}/message", json={"message": "my name is Ahmad"})
    remembered = user_store.get(key)
    remembered.display_name = "Ahmad"
    user_store.save(remembered)

    client.post(f"/api/chat/{key}/reset")

    stored = user_store.get(key)
    assert stored.bot_id is None
    assert stored.history == []
    assert stored.display_name == "Ahmad"
    assert _identify(client, key).json()["bot"] is None


def test_restarting_a_number_we_have_never_met_writes_nothing(client):
    client.post("/api/chat/60129990111/reset")

    assert user_store.get("60129990111") is None
