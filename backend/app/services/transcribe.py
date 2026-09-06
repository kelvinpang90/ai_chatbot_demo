from __future__ import annotations

import httpx

from app.config import settings

# A voice note is a customer waiting in a chat, but it is also a file that has to
# be uploaded and decoded before anyone can answer it. Longer than the 10s the
# messages endpoint runs on, same reasoning as `whatsapp_media`.
TRANSCRIBE_TIMEOUT_SECONDS = 60

TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"

# Malaysian customers switch language mid-sentence -- "boleh tak you hantar
# invoice tu" is one ordinary utterance. Left to itself the model settles on a
# language for the whole clip and transliterates the rest of it, so it is told
# what it is listening to instead. This is a hint, not a constraint: it costs
# nothing when the customer speaks one language throughout.
LANGUAGE_HINT = (
    "A customer in Malaysia speaking to a shop, mixing English, Malay and Chinese "
    "in the same sentence."
)

# What OpenAI decides the audio format from -- the filename's extension, not the
# mime type sent alongside it. An extension it does not know is a 400 that says
# nothing useful, so the mapping is explicit and anything missing from it is
# refused here, where we can still say why.
EXTENSION_BY_MIME = {
    "audio/ogg": "ogg",
    "audio/oga": "oga",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/flac": "flac",
}

TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL)


class TranscriptionError(RuntimeError):
    """Anything that stopped a voice note becoming words.

    The same boundary the back-office clients and `whatsapp_media` draw: without
    it, a `ConnectError` from a transcription provider reaches the webhook as an
    unhandled exception and the customer gets silence instead of "please type it".
    """


class UnsupportedAudioError(TranscriptionError):
    """A format we will not get an answer for, recognised before we pay for one."""


def _extension_for(mime_type: str) -> str:
    """The filename extension this audio has to arrive under.

    WhatsApp sends voice notes as `audio/ogg; codecs=opus`; the parameters after
    the semicolon are part of the header, not part of the type.
    """
    base = mime_type.split(";")[0].strip().lower()
    extension = EXTENSION_BY_MIME.get(base)
    if not extension:
        raise UnsupportedAudioError(f"cannot transcribe audio of type '{mime_type}'")
    return extension


class Transcriber:
    """Speech in, text out. The one thing a provider has to do.

    A class with a single method rather than a bare function so that swapping
    OpenAI for a self-hosted model is writing one more of these and reassigning
    `transcriber` below -- no caller changes, no import changes.
    """

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        raise NotImplementedError


class WhisperTranscriber(Transcriber):
    """OpenAI's hosted transcription endpoint.

    Spoken to over httpx rather than through the `openai` package: this is one
    multipart POST, and every other outbound call in this service already goes
    through httpx, so a second HTTP client would be a dependency and a second set
    of failure modes bought for nothing.
    """

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        if not settings.openai_api_key:
            raise TranscriptionError("OPENAI_API_KEY is not set")
        if not audio:
            raise TranscriptionError("there is no audio to transcribe")

        filename = f"voice-note.{_extension_for(mime_type)}"
        try:
            response = httpx.post(
                TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data={
                    "model": settings.transcription_model,
                    "prompt": LANGUAGE_HINT,
                    "response_format": "json",
                },
                files={"file": (filename, audio, mime_type)},
                timeout=TRANSCRIBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except TRANSPORT_ERRORS as exc:
            raise TranscriptionError(f"transcription request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise TranscriptionError(f"transcription did not answer with JSON: {exc}") from exc

        text = body.get("text")
        if not isinstance(text, str):
            raise TranscriptionError("transcription answered without a 'text' field")
        return text.strip()


# The provider in use. Reassign to swap; nothing else imports the class.
transcriber: Transcriber = WhisperTranscriber()


def transcribe(audio: bytes, mime_type: str) -> str:
    """The whole interface: bytes and their type in, what was said out.

    An empty string means the request succeeded and there was nothing audible in
    the clip -- a real outcome for a voice note recorded by accident, and one the
    caller has to answer differently from a failure.
    """
    return transcriber.transcribe(audio, mime_type)
