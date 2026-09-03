from unittest.mock import patch

from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.main import app
from app.routers.whatsapp_webhook import (
    _extract_messages,
    _resolve_quick_question,
    _truncate,
    dispatch_message,
)
from app.services import llm, outbox
from app.session_store import session_store

client = TestClient(app)


def test_truncate_leaves_short_text_untouched():
    assert _truncate("hello", 24) == "hello"


def test_truncate_shortens_long_text_with_ellipsis():
    text = "a" * 30
    result = _truncate(text, 24)
    assert len(result) == 24
    assert result.endswith("…")


def test_extract_messages_reads_nested_meta_payload():
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{"id": "wamid.1"}, {"id": "wamid.2"}]}}]}]
    }
    messages = _extract_messages(payload)
    assert [m["id"] for m in messages] == ["wamid.1", "wamid.2"]


def test_extract_messages_handles_missing_messages_key():
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "s1"}]}}]}]}
    assert _extract_messages(payload) == []


def test_resolve_quick_question_returns_text_for_valid_index():
    assert _resolve_quick_question("retail", "qq:0") is not None


def test_resolve_quick_question_returns_none_for_bad_id():
    assert _resolve_quick_question("retail", "not-a-qq-id") is None
    assert _resolve_quick_question("retail", "qq:999") is None
    assert _resolve_quick_question("does-not-exist", "qq:0") is None


def test_verify_webhook_get_returns_challenge_when_token_matches():
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.whatsapp_verify_token,
            "hub.challenge": "abc123",
        },
    )
    assert response.status_code == 200
    assert response.text == "abc123"


def test_verify_webhook_get_rejects_wrong_token():
    response = client.get(
        "/webhook/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "definitely-wrong", "hub.challenge": "abc123"},
    )
    assert response.status_code == 403


# -- files a tool produced travelling with the reply --------------------------
#
# The seam between `app.services.outbox` and this router: a tool cannot send a
# WhatsApp message itself, so it leaves the file here and `dispatch_message` is
# supposed to pick it up. Both halves look correct in isolation whether or not
# they are connected, which is what these two are for.


def _text_message(phone: str, body: str) -> dict:
    return {"id": f"wamid.{phone}.1", "from": phone, "type": "text", "text": {"body": body}}


def _in_conversation(phone: str) -> None:
    """Skip the menu and the identity picker; those have their own tests."""
    session = session_store.get_or_create(phone)
    session.bot_id = "retail"
    session.identity_id = get_bot("retail").identities[0].id


def test_a_file_a_tool_produced_is_sent_after_the_words_explaining_it():
    phone = "60129990001"
    _in_conversation(phone)

    def reply_and_attach(*_args, **_kwargs) -> str:
        outbox.add(outbox.Attachment("media-1", "INV-2026-0007.pdf", "your e-Invoice"))
        return "Here is your invoice."

    with patch.object(llm, "get_reply", side_effect=reply_and_attach):
        sent = dispatch_message(_text_message(phone, "send me the invoice"))

    words, document = sent
    assert words["type"] == "text"
    assert document["type"] == "document"
    assert document["to"] == phone
    assert document["document"]["filename"] == "INV-2026-0007.pdf"


def test_a_file_does_not_leak_from_one_conversation_into_the_next():
    """The outbox is opened per inbound message. Left over, an invoice would be
    sent a second time -- to whoever wrote next."""
    first, second = "60129990002", "60129990003"
    _in_conversation(first)
    _in_conversation(second)

    def attach_once(*_args, **_kwargs) -> str:
        outbox.add(outbox.Attachment("media-2", "INV-2026-0008.pdf", ""))
        return "Sent."

    with patch.object(llm, "get_reply", side_effect=attach_once):
        dispatch_message(_text_message(first, "invoice please"))
    with patch.object(llm, "get_reply", return_value="Anything else?"):
        sent = dispatch_message(_text_message(second, "hello"))

    assert [message["type"] for message in sent] == ["text"]
