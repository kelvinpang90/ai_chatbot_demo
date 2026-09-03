from __future__ import annotations

import hashlib
import hmac
import re

import httpx

from app.config import settings

GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
REQUEST_TIMEOUT_SECONDS = 10


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


def build_text_message(to: str, text: str) -> dict:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": markdown_to_whatsapp(text)},
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
        "body": {"text": body_text},
        "action": {"button": button_text, "sections": sections},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}

    return {
        "messaging_product": "whatsapp",
        "to": to,
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
        "to": to,
        "type": "document",
        "document": document,
    }


def build_quick_reply_buttons(to: str, body_text: str, buttons: list[dict]) -> dict:
    """buttons: [{"id": str, "title": str}, ...]. Meta allows at most 3 reply buttons per message."""
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }


def send_raw(payload: dict) -> httpx.Response:
    return httpx.post(_messages_url(), headers=_headers(), json=payload, timeout=REQUEST_TIMEOUT_SECONDS)


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
