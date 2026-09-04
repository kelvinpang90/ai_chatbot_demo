import hashlib
import hmac
from unittest.mock import patch

import httpx
import pytest

from app.services import whatsapp


def _ok():
    """What Meta returns when it accepts a message."""
    return patch.object(whatsapp.httpx, "post", return_value=httpx.Response(200))

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
    with _ok() as mock_post:
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

    with _ok() as mock_post:
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

    with _ok() as mock_post:
        whatsapp.send_quick_reply_buttons("+60123456789", "Quick questions", buttons)

    body = mock_post.call_args.kwargs["json"]
    reply_buttons = body["interactive"]["action"]["buttons"]
    assert len(reply_buttons) == 3
    assert reply_buttons[0] == {"type": "reply", "reply": {"id": "q0", "title": "Question 0"}}


# -- nothing leaves here unchecked, and nothing is refused in silence ----------
#
# A customer once sat looking at a chat where no reply ever arrived. Meta had
# answered 400 -- the reply text was empty -- and every layer of ours shrugged:
# `send_raw` returned the response, nobody read it, and the only trace was an
# httpx line at INFO that looks exactly like a success. These cover both halves
# of that: the payload never gets built, and a rejection is never swallowed.


def test_a_rejected_message_raises_instead_of_being_returned():
    refusal = httpx.Response(400, text='{"error":{"message":"(#100) Invalid parameter"}}')

    with patch.object(whatsapp.httpx, "post", return_value=refusal):
        with pytest.raises(whatsapp.WhatsAppSendError) as failure:
            whatsapp.send_text_message("60123456789", "hello")

    # Meta's own words have to survive into the log, or whoever reads it later
    # knows only that something was refused.
    assert "400" in str(failure.value)
    assert "Invalid parameter" in str(failure.value)
    assert "text" in str(failure.value)  # which kind of message it was


def test_an_empty_reply_never_becomes_a_payload_at_all():
    """The exact shape of the outage: Meta answers a bare 400 and explains
    nothing, so the refusal has to happen here where the caller is still known."""
    for blank in ("", "   ", "\n\n"):
        with pytest.raises(whatsapp.UnsendableMessage):
            whatsapp.build_text_message("60123456789", blank)


def test_an_over_long_reply_is_trimmed_to_what_meta_accepts():
    """Also a 400, and one no caller should have to remember to avoid."""
    body = whatsapp.build_text_message("60123456789", "a" * 9000)["text"]["body"]

    assert len(body) == whatsapp.MAX_TEXT_BODY_CHARS
    assert body.endswith("…")


def test_the_interactive_builders_hold_to_the_same_contract():
    """Every producer of text goes through one door, including the menus."""
    with pytest.raises(whatsapp.UnsendableMessage):
        whatsapp.build_interactive_list("60123456789", "", "Select", [])
    with pytest.raises(whatsapp.UnsendableMessage):
        whatsapp.build_quick_reply_buttons("60123456789", "", [])

    long_list = whatsapp.build_interactive_list("60123456789", "b" * 4000, "Select", [])
    assert len(long_list["interactive"]["body"]["text"]) == whatsapp.MAX_INTERACTIVE_BODY_CHARS
