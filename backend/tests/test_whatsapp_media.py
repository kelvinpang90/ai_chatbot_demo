from unittest.mock import Mock, patch

import httpx
import pytest

from app.config import settings
from app.services import whatsapp_media

MEDIA_ID = "media-abc-123"
DOWNLOAD_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=media-abc-123"


def _json_response(payload: dict, headers: dict | None = None) -> Mock:
    response = Mock(spec=httpx.Response)
    response.json.return_value = payload
    response.headers = headers or {}
    response.raise_for_status.return_value = None
    return response


def _binary_response(content: bytes, content_type: str = "application/octet-stream") -> Mock:
    response = Mock(spec=httpx.Response)
    response.content = content
    response.headers = {"content-type": content_type}
    response.raise_for_status.return_value = None
    return response


def test_fetch_media_looks_up_metadata_then_downloads_with_token():
    meta = _json_response(
        {"url": DOWNLOAD_URL, "mime_type": "image/jpeg", "file_size": 2048}
    )
    binary = _binary_response(b"\xff\xd8\xff-jpeg-bytes")

    with patch.object(whatsapp_media.httpx, "get", side_effect=[meta, binary]) as mock_get:
        media = whatsapp_media.fetch_media(MEDIA_ID)

    lookup_call, download_call = mock_get.call_args_list
    assert lookup_call.args[0] == f"{whatsapp_media.GRAPH_API_BASE}/{MEDIA_ID}"
    assert download_call.args[0] == DOWNLOAD_URL
    # The CDN link is short-lived but still refuses an unauthenticated request.
    for call in (lookup_call, download_call):
        assert call.kwargs["headers"]["Authorization"].startswith("Bearer ")
        assert "Content-Type" not in call.kwargs["headers"]

    assert media.content == b"\xff\xd8\xff-jpeg-bytes"
    assert media.mime_type == "image/jpeg"


def test_fetch_media_falls_back_to_the_download_content_type():
    meta = _json_response({"url": DOWNLOAD_URL, "file_size": 10})
    binary = _binary_response(b"%PDF-1.7", content_type="application/pdf")

    with patch.object(whatsapp_media.httpx, "get", side_effect=[meta, binary]):
        media = whatsapp_media.fetch_media(MEDIA_ID)

    assert media.mime_type == "application/pdf"


def test_fetch_media_refuses_oversized_files_before_downloading():
    oversized = settings.whatsapp_media_max_bytes + 1
    meta = _json_response({"url": DOWNLOAD_URL, "mime_type": "video/mp4", "file_size": oversized})

    with patch.object(whatsapp_media.httpx, "get", side_effect=[meta]) as mock_get:
        with pytest.raises(whatsapp_media.MediaTooLargeError):
            whatsapp_media.fetch_media(MEDIA_ID)

    assert mock_get.call_count == 1  # never reached the download


def test_upload_media_posts_multipart_and_returns_the_id():
    with patch.object(
        whatsapp_media.httpx, "post", return_value=_json_response({"id": "uploaded-42"})
    ) as mock_post:
        media_id = whatsapp_media.upload_media(b"%PDF-1.7", "application/pdf", "invoice.pdf")

    assert media_id == "uploaded-42"
    assert mock_post.call_args.args[0] == whatsapp_media._media_url()
    assert mock_post.call_args.kwargs["data"]["messaging_product"] == "whatsapp"
    assert mock_post.call_args.kwargs["files"]["file"] == (
        "invoice.pdf",
        b"%PDF-1.7",
        "application/pdf",
    )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"].startswith("Bearer ")
    # httpx sets the multipart boundary itself; forcing a Content-Type breaks the upload.
    assert "Content-Type" not in headers


def test_send_message_posts_the_payload_to_the_messages_endpoint():
    payload = {"messaging_product": "whatsapp", "to": "+60123456789", "type": "text"}

    with patch.object(whatsapp_media.httpx, "post") as mock_post:
        whatsapp_media.send_message(payload)

    assert mock_post.call_args.args[0].endswith(
        f"/{settings.whatsapp_phone_number_id}/messages"
    )
    assert mock_post.call_args.kwargs["json"] == payload
    assert mock_post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")
