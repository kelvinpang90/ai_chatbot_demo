from __future__ import annotations

import hashlib
import hmac
import re

import httpx

from app.config import settings
from app.services import phone

GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
REQUEST_TIMEOUT_SECONDS = 10

# Meta's own caps on the text a message may carry. Going over is a 400, which is
# indistinguishable from every other 400 unless we keep inside them ourselves.
MAX_TEXT_BODY_CHARS = 4096
MAX_INTERACTIVE_BODY_CHARS = 1024

# How much of Meta's rejection to quote back into the log. Their errors carry a
# message, a code and a trace id, and all three are worth having.
MAX_ERROR_CHARS = 500


def _recipient(to: str) -> dict:
    """Address one outgoing message.

    A phone number goes in `to`, the field this API has always had. A customer
    who has hidden their number behind a username reaches us as a BSUID, and
    Meta addresses those with `recipient` instead.

    NOT YET VERIFIED AGAINST A LIVE SEND. Meta's own send-message guide still
    documents `to` alone; `recipient` comes from their SDK reference. Left as a
    single decision in one place for exactly that reason -- and a wrong guess is
    now a loud `WhatsAppSendError` from `send_raw` on the first such message,
    rather than a customer nobody can answer.
    """
    return {"recipient": to} if phone.is_bsuid(to) else {"to": to}


class UnsendableMessage(ValueError):
    """We were asked to build a message WhatsApp would refuse.

    Always a bug on our side rather than a fact about the customer, so it is
    raised where the message is built: the alternative is Meta answering a bare
    400 several layers away, with nothing left to say which of our callers
    produced it.
    """


class WhatsAppSendError(RuntimeError):
    """Meta refused to deliver a message. Carries what they said about it."""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }


def _messages_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.whatsapp_phone_number_id}/messages"


def verify_signature(payload: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 header against the raw request body."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def markdown_to_whatsapp(text: str) -> str:
    """Convert the small subset of markdown Claude tends to output into WhatsApp's own syntax."""
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)  # **bold** -> *bold*
    text = re.sub(r"`(.+?)`", r"```\1```", text)  # `code` -> ```code```
    return text


def _body(text: str, limit: int) -> str:
    """The text as WhatsApp will actually accept it.

    Every message we send ends up here, which is the point: the channel's rules
    belong at the one door out, not repeated at each of the growing number of
    places that produce text -- a model reply, a transcription, a proactive
    notification. A caller cannot forget a rule it never has to know.

    Empty is refused rather than repaired. Meta answers an empty body with a
    plain 400 and no explanation, and the only way to produce one is a bug
    upstream; sending filler in its place would hide that bug behind a message
    the customer cannot act on either.
    """
    text = markdown_to_whatsapp(text or "").strip()
    if not text:
        raise UnsendableMessage("refusing to send a message with no text in it")
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def build_text_message(to: str, text: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        **_recipient(to),
        "type": "text",
        "text": {"body": _body(text, MAX_TEXT_BODY_CHARS)},
    }


def build_interactive_list(
    to: str,
    body_text: str,
    button_text: str,
    sections: list[dict],
    header_text: str | None = None,
) -> dict:
    """sections follows Meta's format: [{"title": str, "rows": [{"id": str, "title": str, "description": str}]}]."""
    interactive: dict = {
        "type": "list",
        "body": {"text": _body(body_text, MAX_INTERACTIVE_BODY_CHARS)},
        "action": {"button": button_text, "sections": sections},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}

    return {
        "messaging_product": "whatsapp",
        **_recipient(to),
        "type": "interactive",
        "interactive": interactive,
    }


def build_document_message(to: str, media_id: str, filename: str, caption: str = "") -> dict:
    """Send a file already uploaded to Meta, by reference.

    `filename` is what the customer sees in the chat and what their phone saves,
    so it carries the document number rather than a temporary name. The caption
    is optional at Meta's end and omitted rather than sent empty.
    """
    document: dict = {"id": media_id, "filename": filename}
    if caption:
        document["caption"] = caption
    return {
        "messaging_product": "whatsapp",
        **_recipient(to),
        "type": "document",
        "document": document,
    }


def build_quick_reply_buttons(to: str, body_text: str, buttons: list[dict]) -> dict:
    """buttons: [{"id": str, "title": str}, ...]. Meta allows at most 3 reply buttons per message."""
    return {
        "messaging_product": "whatsapp",
        **_recipient(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": _body(body_text, MAX_INTERACTIVE_BODY_CHARS)},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }


def send_raw(payload: dict) -> httpx.Response:
    """Hand one built payload to Meta, and refuse to shrug off a rejection.

    Returning the response and letting callers ignore it is how a customer came
    to sit in silence while the log showed nothing but a routine httpx line at
    INFO: Meta had answered 400 and no code anywhere looked. A raise here lands
    in the caller's handler as a logged traceback carrying Meta's own words.
    """
    response = httpx.post(_messages_url(), headers=_headers(), json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.is_error:
        raise WhatsAppSendError(
            f"WhatsApp refused a {payload.get('type', '?')} message "
            f"(HTTP {response.status_code}): {response.text[:MAX_ERROR_CHARS]}"
        )
    return response


def send_text_message(to: str, text: str) -> httpx.Response:
    return send_raw(build_text_message(to, text))


def send_interactive_list(
    to: str,
    body_text: str,
    button_text: str,
    sections: list[dict],
    header_text: str | None = None,
) -> httpx.Response:
    return send_raw(build_interactive_list(to, body_text, button_text, sections, header_text))


def send_quick_reply_buttons(to: str, body_text: str, buttons: list[dict]) -> httpx.Response:
    return send_raw(build_quick_reply_buttons(to, body_text, buttons))
