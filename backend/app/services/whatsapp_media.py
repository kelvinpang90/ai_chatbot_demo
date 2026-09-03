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


class MediaError(RuntimeError):
    """Anything that stopped a file moving between us and Meta.

    The same boundary `JsonApiClient` draws in front of the back offices, for the
    same reason: without it every caller has to remember that this module talks
    to the network through httpx, and the first one to forget lets a
    `ConnectError` out of a tool and into the customer's chat as a dead bot.
    """


class MediaTooLargeError(MediaError):
    """Meta accepts attachments far bigger than we can usefully hand to the model."""


# Everything httpx can throw at a caller that reads its response whole. Same list
# `api_client` keeps for the same reason: `InvalidURL` does not derive from
# `HTTPError`, so a malformed phone number id escapes a naive catch.
TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL)


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


def _media_url() -> str:
    return f"{GRAPH_API_BASE}/{settings.whatsapp_phone_number_id}/media"


def _get(url: str) -> httpx.Response:
    try:
        response = httpx.get(url, headers=_auth_headers(), timeout=MEDIA_TIMEOUT_SECONDS)
        response.raise_for_status()
    except TRANSPORT_ERRORS as exc:
        raise MediaError(f"GET {url} failed: {exc}") from exc
    return response


def _json(response: httpx.Response) -> dict:
    """Meta's answer, or a MediaError if something in front of it answered instead."""
    try:
        return response.json()
    except ValueError as exc:
        raise MediaError(f"media endpoint did not answer with JSON: {exc}") from exc


def fetch_media(media_id: str) -> Media:
    """Download an inbound attachment. Two hops: metadata for the URL, then the bytes."""
    meta = _json(_get(f"{GRAPH_API_BASE}/{media_id}"))
    download_url = meta.get("url")
    if not download_url:
        raise MediaError(f"media {media_id} has no download url")

    file_size = int(meta.get("file_size") or 0)
    if file_size > settings.whatsapp_media_max_bytes:
        raise MediaTooLargeError(
            f"media {media_id} is {file_size} bytes, over the "
            f"{settings.whatsapp_media_max_bytes} byte limit"
        )

    # The lookup URL is short-lived and, unlike a normal CDN link, still wants the token.
    binary_response = _get(download_url)

    mime_type = meta.get("mime_type") or binary_response.headers.get(
        "content-type", "application/octet-stream"
    )
    return Media(content=binary_response.content, mime_type=mime_type)


def upload_media(content: bytes, mime_type: str, filename: str) -> str:
    """Hand Meta a file and get back the media_id an outbound message attaches by reference."""
    try:
        response = httpx.post(
            _media_url(),
            headers=_auth_headers(),
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, content, mime_type)},
            timeout=MEDIA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except TRANSPORT_ERRORS as exc:
        raise MediaError(f"uploading {filename} failed: {exc}") from exc

    media_id = _json(response).get("id")
    if not media_id:
        raise MediaError(f"upload of {filename} returned no media id")
    return media_id


def send_message(payload: dict) -> httpx.Response:
    """Send on our own initiative (pushes, follow-ups).

    Replies to an inbound message keep going through the webhook's synchronous path;
    this is the same endpoint, named for the caller that has no request to reply to.
    """
    return send_raw(payload)
