import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _internal_secret(monkeypatch):
    monkeypatch.setattr(settings, "internal_shared_secret", "test-internal-secret")


def _text_message(text: str, message_id: str = "wamid.internal-1") -> dict:
    return {"id": message_id, "from": "+60123456789", "type": "text", "text": {"body": text}}


def test_rejects_missing_secret_header():
    response = client.post("/internal/whatsapp/inbound", json={"message": _text_message("hi")})
    assert response.status_code == 401


def test_rejects_wrong_secret_header():
    response = client.post(
        "/internal/whatsapp/inbound",
        json={"message": _text_message("hi")},
        headers={"X-Internal-Secret": "wrong-secret"},
    )
    assert response.status_code == 401


def test_rejects_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "internal_shared_secret", "")
    response = client.post(
        "/internal/whatsapp/inbound",
        json={"message": _text_message("hi")},
        headers={"X-Internal-Secret": ""},
    )
    assert response.status_code == 401


def test_rejects_missing_message_field():
    response = client.post(
        "/internal/whatsapp/inbound",
        json={},
        headers={"X-Internal-Secret": "test-internal-secret"},
    )
    assert response.status_code == 400


def test_returns_bot_list_payload_for_new_phone():
    response = client.post(
        "/internal/whatsapp/inbound",
        json={"message": _text_message("hi", message_id="wamid.internal-new-phone")},
        headers={"X-Internal-Secret": "test-internal-secret"},
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["type"] == "interactive"
    assert messages[0]["interactive"]["type"] == "list"


def test_duplicate_message_id_returns_empty_messages():
    payload = {"message": _text_message("hi", message_id="wamid.internal-dup")}
    headers = {"X-Internal-Secret": "test-internal-secret"}

    first = client.post("/internal/whatsapp/inbound", json=payload, headers=headers)
    second = client.post("/internal/whatsapp/inbound", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["messages"] == []
