import hashlib
import hmac
from unittest.mock import patch

from app.services import whatsapp

APP_SECRET = "test-app-secret"


def _sign(payload: bytes, secret: str = APP_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_accepts_correct_signature():
    payload = b'{"hello": "world"}'
    signature = _sign(payload)
    assert whatsapp.verify_signature(payload, signature, APP_SECRET) is True


def test_verify_signature_rejects_wrong_secret():
    payload = b'{"hello": "world"}'
    signature = _sign(payload, secret="wrong-secret")
    assert whatsapp.verify_signature(payload, signature, APP_SECRET) is False


def test_verify_signature_rejects_tampered_payload():
    payload = b'{"hello": "world"}'
    signature = _sign(payload)
    tampered = b'{"hello": "mallory"}'
    assert whatsapp.verify_signature(tampered, signature, APP_SECRET) is False


def test_verify_signature_rejects_missing_or_malformed_header():
    payload = b'{"hello": "world"}'
    assert whatsapp.verify_signature(payload, None, APP_SECRET) is False
    assert whatsapp.verify_signature(payload, "not-a-valid-header", APP_SECRET) is False


def test_markdown_to_whatsapp_converts_bold_and_code():
    text = whatsapp.markdown_to_whatsapp("Your order **ORD-123** is `out for delivery`.")
    assert text == "Your order *ORD-123* is ```out for delivery```."


def test_markdown_to_whatsapp_leaves_plain_text_untouched():
    text = whatsapp.markdown_to_whatsapp("Hello, how can I help you today?")
    assert text == "Hello, how can I help you today?"


def test_send_text_message_posts_expected_body():
    with patch.object(whatsapp.httpx, "post") as mock_post:
        whatsapp.send_text_message("+60123456789", "Your order **ORD-1** is ready")

    args, kwargs = mock_post.call_args
    assert args[0] == whatsapp._messages_url()
    body = kwargs["json"]
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "+60123456789"
    assert body["type"] == "text"
    assert body["text"]["body"] == "Your order *ORD-1* is ready"
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")


def test_send_interactive_list_posts_expected_structure():
    sections = [{"title": "Bots", "rows": [{"id": "retail", "title": "Retail", "description": "Shop"}]}]

    with patch.object(whatsapp.httpx, "post") as mock_post:
        whatsapp.send_interactive_list(
            "+60123456789", "Pick a bot", "Choose", sections, header_text="Welcome"
        )

    body = mock_post.call_args.kwargs["json"]
    assert body["type"] == "interactive"
    assert body["interactive"]["type"] == "list"
    assert body["interactive"]["header"] == {"type": "text", "text": "Welcome"}
    assert body["interactive"]["action"]["button"] == "Choose"
    assert body["interactive"]["action"]["sections"] == sections


def test_send_quick_reply_buttons_caps_at_three():
    buttons = [{"id": f"q{i}", "title": f"Question {i}"} for i in range(5)]

    with patch.object(whatsapp.httpx, "post") as mock_post:
        whatsapp.send_quick_reply_buttons("+60123456789", "Quick questions", buttons)

    body = mock_post.call_args.kwargs["json"]
    reply_buttons = body["interactive"]["action"]["buttons"]
    assert len(reply_buttons) == 3
    assert reply_buttons[0] == {"type": "reply", "reply": {"id": "q0", "title": "Question 0"}}
