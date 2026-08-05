from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers.whatsapp_webhook import _extract_messages, _resolve_quick_question, _truncate

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
