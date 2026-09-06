from unittest.mock import Mock, patch

import httpx
import pytest

from app.config import settings
from app.services import transcribe

# What WhatsApp actually puts on a voice note. The codecs parameter is the part
# that used to be the whole problem: it is a valid mime header and an invalid
# dictionary key.
VOICE_NOTE_MIME = "audio/ogg; codecs=opus"
OGG_BYTES = b"OggS\x00\x02-not-really-opus"


@pytest.fixture
def api_key():
    """A transcriber that will actually attempt a call.

    Nothing under `backend/` sets OPENAI_API_KEY, so without this every test
    would be asserting against the no-credentials path -- the same trap
    conftest's `erp_credentials` exists for.
    """
    with patch.object(settings, "openai_api_key", "sk-not-a-real-key"):
        yield


def _answer(payload: dict) -> Mock:
    response = Mock(spec=httpx.Response)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_a_voice_note_is_uploaded_under_a_filename_openai_can_read(api_key):
    """OpenAI reads the format off the extension, not off the mime type, so the
    filename is the one part of this request that cannot be cosmetic."""
    with patch.object(transcribe.httpx, "post", return_value=_answer({"text": "hello"})) as post:
        said = transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)

    filename, content, mime_type = post.call_args.kwargs["files"]["file"]
    assert filename.endswith(".ogg")
    assert content == OGG_BYTES
    assert mime_type == VOICE_NOTE_MIME
    assert said == "hello"


def test_the_call_carries_the_key_the_model_and_the_language_hint(api_key):
    with patch.object(transcribe.httpx, "post", return_value=_answer({"text": "ok"})) as post:
        transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)

    call = post.call_args
    assert call.args[0] == transcribe.TRANSCRIPTION_URL
    assert call.kwargs["headers"]["Authorization"] == "Bearer sk-not-a-real-key"
    assert call.kwargs["data"]["model"] == settings.transcription_model
    # Without it the model settles on one language and transliterates the rest,
    # which is exactly the sentence a Malaysian customer speaks.
    assert call.kwargs["data"]["prompt"] == transcribe.LANGUAGE_HINT


def test_every_audio_type_whatsapp_sends_maps_to_an_extension_openai_accepts(api_key):
    """Meta's own list of inbound audio types, minus the one we cannot use."""
    for mime, expected in [
        ("audio/ogg; codecs=opus", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "mp4"),
        ("audio/aac", "m4a"),
        ("audio/amr", None),
    ]:
        if expected is None:
            with pytest.raises(transcribe.UnsupportedAudioError):
                transcribe._extension_for(mime)
        else:
            assert transcribe._extension_for(mime) == expected


def test_an_uppercase_or_padded_mime_type_is_still_recognised(api_key):
    assert transcribe._extension_for(" AUDIO/OGG ; codecs=opus") == "ogg"


def test_a_format_we_cannot_transcribe_is_refused_before_it_is_paid_for(api_key):
    """AMR is a type WhatsApp will send and OpenAI will not read. Sending it
    anyway buys a 400 that says nothing about which of the two ends was wrong."""
    with patch.object(transcribe.httpx, "post") as post:
        with pytest.raises(transcribe.UnsupportedAudioError):
            transcribe.transcribe(b"#!AMR\n", "audio/amr")

    post.assert_not_called()


def test_a_missing_api_key_is_a_transcription_error_not_a_401():
    with patch.object(settings, "openai_api_key", ""):
        with patch.object(transcribe.httpx, "post") as post:
            with pytest.raises(transcribe.TranscriptionError):
                transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)

    post.assert_not_called()


def test_an_empty_clip_is_refused_without_a_round_trip(api_key):
    with patch.object(transcribe.httpx, "post") as post:
        with pytest.raises(transcribe.TranscriptionError):
            transcribe.transcribe(b"", VOICE_NOTE_MIME)

    post.assert_not_called()


def test_a_transport_failure_does_not_escape_as_an_httpx_error(api_key):
    """The boundary. An httpx error out of here reaches the webhook unhandled and
    the customer gets silence instead of "please type it"."""
    with patch.object(transcribe.httpx, "post", side_effect=httpx.ConnectError("no route")):
        with pytest.raises(transcribe.TranscriptionError):
            transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)


def test_a_body_that_is_not_json_is_a_transcription_error(api_key):
    """A proxy or a rate limiter answering in HTML in front of the API."""
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.side_effect = ValueError("not json")

    with patch.object(transcribe.httpx, "post", return_value=response):
        with pytest.raises(transcribe.TranscriptionError):
            transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)


def test_an_answer_without_a_text_field_is_a_transcription_error(api_key):
    with patch.object(transcribe.httpx, "post", return_value=_answer({"error": "quota"})):
        with pytest.raises(transcribe.TranscriptionError):
            transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME)


def test_silence_comes_back_as_an_empty_string_not_as_a_failure(api_key):
    """A voice note recorded by accident is a real thing a customer sends, and
    the caller answers it differently from a provider that fell over."""
    with patch.object(transcribe.httpx, "post", return_value=_answer({"text": "  \n "})):
        assert transcribe.transcribe(OGG_BYTES, VOICE_NOTE_MIME) == ""


def test_swapping_the_provider_is_one_assignment():
    """The whole reason this is a class. A self-hosted model later must not mean
    touching the webhook."""

    class Stub(transcribe.Transcriber):
        def transcribe(self, audio: bytes, mime_type: str) -> str:
            return f"heard {len(audio)} bytes of {mime_type}"

    with patch.object(transcribe, "transcriber", Stub()):
        assert transcribe.transcribe(b"1234", "audio/ogg") == "heard 4 bytes of audio/ogg"


def test_the_base_class_refuses_to_be_used_as_a_provider():
    with pytest.raises(NotImplementedError):
        transcribe.Transcriber().transcribe(OGG_BYTES, VOICE_NOTE_MIME)
