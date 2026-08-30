from __future__ import annotations

from typing import NamedTuple

import httpx

from app.config import settings
from app.services.whatsapp import GRAPH_API_BASE, send_raw

# Media transfers move real files, not a few hundred bytes of JSON, so they get
# a longer leash than the 10s the messages endpoint runs on.
MEDIA_TIMEOUT_SECONDS = 30


class Media(NamedTuple):
    content: bytes
    mime_type: str


class MediaTooLargeError(RuntimeError):
    """Meta accepts attachments far bigger than we can usefully hand to the model."""


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def _media_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.whatsapp_phone_number_id}/media"


def fetch_media(media_id: str) -> Media:
    """Download an inbound attachment. Two hops: metadata for the URL, then the bytes."""
    meta_response = httpx.get(
        f"{GRAPH_API_BASE}/{media_id}",
        headers=_auth_headers(),
        timeout=MEDIA_TIMEOUT_SECONDS,
    )
    meta_response.raise_for_status()
    meta = meta_response.json()

    file_size = int(meta.get("file_size") or 0)
    if file_size > settings.whatsapp_media_max_bytes:
        raise MediaTooLargeError(
            f"media {media_id} is {file_size} bytes, over the "
            f"{settings.whatsapp_media_max_bytes} byte limit"
        )

    # The lookup URL is short-lived and, unlike a normal CDN link, still wants the token.
    binary_response = httpx.get(
        meta["url"], headers=_auth_headers(), timeout=MEDIA_TIMEOUT_SECONDS
    )
    binary_response.raise_for_status()

    mime_type = meta.get("mime_type") or binary_response.headers.get(
        "content-type", "application/octet-stream"
    )
    return Media(content=binary_response.content, mime_type=mime_type)


def upload_media(content: bytes, mime_type: str, filename: str) -> str:
    """Hand Meta a file and get back the media_id an outbound message attaches by reference."""
    response = httpx.post(
        _media_url(),
        headers=_auth_headers(),
        data={"messaging_product": "whatsapp", "type": mime_type},
        files={"file": (filename, content, mime_type)},
        timeout=MEDIA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["id"]


def send_message(payload: dict) -> httpx.Response:
    """Send on our own initiative (pushes, follow-ups).

    Replies to an inbound message keep going through the webhook's synchronous path;
    this is the same endpoint, named for the caller that has no request to reply to.
    """
    return send_raw(payload)
