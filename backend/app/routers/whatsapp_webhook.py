from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.bots.registry import BotConfig, get_bot, list_bots
from app.config import settings
from app.console import events
from app.services import (
    audit,
    doc_store,
    handover,
    llm,
    notify,
    outbox,
    transcribe,
    whatsapp,
    whatsapp_media,
)
from app.services.user_store import user_store
from app.session_store import session_store
from app.tools import erp

router = APIRouter(prefix="/webhook/whatsapp")
logger = logging.getLogger(__name__)

# The canned replies, in all three languages the demo is sold in.
#
# These are the only things a customer reads that the model did not write, and
# they turn up mid-conversation -- so they cannot be answered in the language the
# customer is writing in the way every other reply is. Seen on a real phone on
# 2026-09-11: a conversation in Chinese about a helmet, and then one flat English
# sentence, which reads as the seam it is. `llm.FALLBACK_REPLY` had already
# settled the shape for this; these follow it. Anything added here follows it too.
RATE_LIMIT_MESSAGE = (
    "您今天在这个 demo 的消息次数已用完，请明天再试。 / "
    "You've reached today's message limit for this demo - please try again tomorrow. / "
    "Anda telah mencapai had mesej harian untuk demo ini - sila cuba lagi esok."
)
UNSUPPORTED_TYPE_MESSAGE = (
    "抱歉，这个 demo 只能读文字、语音、图片和 PDF，请直接打字告诉我。 / "
    "Sorry, I can only read text, voice, photo and PDF messages in this demo - "
    "please type your question instead. / "
    "Maaf, demo ini hanya boleh membaca teks, suara, gambar dan PDF - "
    "sila taip soalan anda."
)
# One line for both ways a voice note can come to nothing, because the customer's
# next move is the same either way. Which of the two it was is on the console.
VOICE_UNREADABLE_MESSAGE = (
    "抱歉，这条语音我没听清，请直接打字告诉我。 / "
    "Sorry, I couldn't make out that voice message - please type your question instead. / "
    "Maaf, saya tidak dapat menangkap mesej suara itu - sila taip soalan anda."
)
# Same posture for a photo. Three ways it can come to nothing -- the download
# failed, the file was over the cap, or it is a format the model cannot read --
# and one thing left for the customer to do about any of them.
IMAGE_UNREADABLE_MESSAGE = (
    "抱歉，这张照片我打不开，麻烦再发一次，或者直接说说您看到的是什么。 / "
    "Sorry, I couldn't open that photo - please try sending it again, "
    "or describe what you're seeing. / "
    "Maaf, saya tidak dapat membuka gambar itu - sila hantar semula, "
    "atau ceritakan apa yang anda lihat."
)
# A file has one more way to come to nothing than a photo does -- it can be a
# type the model cannot read at all -- and that one is worth naming, because
# unlike a failed download it tells the customer something they can act on.
DOCUMENT_UNREADABLE_MESSAGE = (
    "抱歉，这个文件我打不开，这个 demo 目前只能读 PDF，麻烦转成 PDF 再发一次。 / "
    "Sorry, I couldn't open that file - this demo can only read PDFs, "
    "so please export it as a PDF and send it again. / "
    "Maaf, saya tidak dapat membuka fail itu - demo ini hanya boleh membaca PDF, "
    "sila hantar semula dalam bentuk PDF."
)
GREETING_SUFFIX_EN = "How can I help you today?"
# Not a tool the model called, but the same thing to the person watching the
# console: a step that took time, against an input, producing an output worth
# reading. Emitted as a tool span so it renders on the director's screen without
# a new event type nothing knows how to draw.
VOICE_TOOL = "voice.transcribe"
NOTHING_AUDIBLE = "(nothing audible)"
# Same reasoning as VOICE_TOOL: a download the customer is waiting on, with an
# input and an outcome, drawn as the span it already is.
IMAGE_TOOL = "image.download"
# What a photo leaves behind in the history the model is replayed next turn. The
# picture itself is gone by then -- see llm.Image -- and without this the turn
# reads as if the customer had sent the caption on its own, or, where there was
# no caption, as if they had sent nothing at all.
PHOTO_MARKER = "[photo]"
# Same reasoning again for a download the customer waits on.
DOCUMENT_TOOL = "document.download"
# The document's stand-in in the history -- and, unlike the photo's, also the
# address the file is filed under: `llm` finds this exact line again on every
# later turn and hangs the PDF back on it. Which is why the filename is in it.
DOCUMENT_MARKER = "[document]"
MENU_KEYWORDS = {"menu", "菜单"}
# Asking for a person, in the words a customer actually uses -- and only when
# they are actually asking. A floor under the `request_human_help` tool rather
# than a replacement for it: the tool is how a bot escalates something it judges
# to be beyond it, and this is how a customer who has stopped wanting to talk to
# a machine gets their way whatever the model thinks, including on the three bots
# that have no tools to call.
#
# Phrases, never bare nouns, and that is the whole of what this list learned the
# hard way. The first version matched "human", "agent" and "人工" as substrings,
# which silences the bot for seven days on:
#   你们这是人工智能吗?            -- "is this an AI?", the single likeliest
#                                     question anybody asks an AI demo
#   I bought it from your agent    -- and realestate's own persona tells the bot
#                                     to offer exactly this word
#   human resources teams
# A customer who wants a person says so with a verb. A customer using one of
# these words about something else never does.
HUMAN_PHRASES = (
    "转人工",
    "找人工",
    "要人工",
    "人工客服",
    "人工服务",
    "找真人",
    "要真人",
    "真人客服",
    "找个人",
    "找同事",
    "speak to a human",
    "talk to a human",
    "speak to a person",
    "talk to a person",
    "speak to someone",
    "talk to someone",
    "real person",
    "human agent",
    "customer service agent",
    "cakap dengan orang",
    "nak orang sebenar",
    "orang sebenar",
)


@router.get("")
def verify_webhook(request: Request) -> Response:
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not whatsapp.verify_signature(raw_body, signature, settings.whatsapp_app_secret):
        logger.warning("Rejected WhatsApp webhook call with invalid signature")
        return Response(status_code=401)

    payload = await request.json()
    for message, contact in _extract_messages(payload):
        background_tasks.add_task(_handle_incoming_message, message, contact)

    return Response(status_code=200)


def _extract_messages(payload: dict) -> list[tuple[dict, dict]]:
    """Each inbound message paired with the contact block describing its sender.

    The contact used to be dropped. It carries the two things a customer who has
    hidden their phone number is known by -- `user_id` and `profile.username` --
    and neither appears on the message itself, so throwing it away left nothing
    to identify such a sender with.
    """
    pairs: list[tuple[dict, dict]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts") or []
            for message in value.get("messages", []):
                pairs.append((message, _contact_for(message, contacts)))
    return pairs


def _contact_for(message: dict, contacts: list[dict]) -> dict:
    """The contact entry describing this message's sender.

    Matched on `wa_id` where there is one to match. A batch normally carries a
    single contact, so one unambiguous entry is taken as the sender's rather
    than dropped for want of a phone number to match it by -- which is exactly
    the case where the phone number is the thing we do not have.
    """
    sender = message.get("from")
    if sender:
        matched = next((c for c in contacts if c.get("wa_id") == sender), None)
        if matched:
            return matched
    return contacts[0] if len(contacts) == 1 else {}


@dataclass(frozen=True)
class Sender:
    """Who wrote in, and what to write back to.

    `key` is both the identifier the record is filed under and the address a
    reply is sent to: the phone number wherever WhatsApp gives us one, and the
    BSUID for a customer who has hidden theirs. One value for both, because a
    record we can find and a customer we cannot answer is no better than neither.
    """

    key: str
    phone: str | None
    user_id: str | None
    username: str | None


def _identify(message: dict, contact: dict) -> Sender | None:
    """Work out who this message is from, or None if it cannot be told.

    The phone number is preferred over the BSUID even though the BSUID is always
    present and never changes. Keying on it would quietly undo the rest of the
    design: the back offices are searched by phone, the web chat in task 33 asks
    for a phone, and a BSUID is scoped to the business portfolio -- so moving
    portfolio, which this project has done once already, would reissue every id
    and forget every customer.
    """
    phone_number = message.get("from")
    profile = contact.get("profile") or {}
    # Meta's docs put the id on the message as `from_user_id` and on the contact
    # as `user_id`. Both are read: this cannot be tried against a live customer
    # yet, and guessing one spelling wrong means dropping the message.
    user_id = message.get("from_user_id") or contact.get("user_id")
    username = profile.get("username") or None
    name = profile.get("name") or None

    if phone_number:
        return Sender(key=phone_number, phone=phone_number, user_id=user_id, username=username or name)
    if user_id:
        return Sender(key=user_id, phone=None, user_id=user_id, username=username or name)
    return None


def _handle_incoming_message(message: dict, contact: dict | None = None) -> None:
    try:
        # Before the work, not after it: a reply that strings together several
        # real ERP calls takes long enough that a silent chat reads as a hung
        # one, and the honest tool calls this project exists to show off would
        # be mistaken for the thing being slow. Deliberately outside
        # `dispatch_message`, which is contracted to send nothing itself --
        # under the gateway path it only returns payloads, and the indicator is
        # a side effect with a different lifetime from a reply.
        whatsapp.send_typing_indicator(str(message.get("id") or ""))
        for payload in dispatch_message(message, contact):
            whatsapp.send_raw(payload)
    except Exception as failure:
        logger.exception("Unhandled error processing WhatsApp message %s", message.get("id"))
        # The customer is looking at a chat where nothing arrived. Say so on the
        # console too: a log line is found afterwards, a console line is seen
        # while the room is still watching.
        events.emit(
            type=events.SEND_FAILED,
            tool="whatsapp.send",
            tool_use_id=str(message.get("id", "")),
            output=f"{type(failure).__name__}: {failure}",
            status="error",
        )


def dispatch_message(message: dict, contact: dict | None = None) -> list[dict]:
    """Process one raw Meta message object and return the reply payload(s) to send.

    Shared by the public Meta-facing webhook above and the internal
    /internal/whatsapp/inbound endpoint (see routers/internal_whatsapp.py) used by
    whatsapp_gateway, so this never calls whatsapp.send_* directly.
    """
    message_id = message.get("id")
    sender = _identify(message, contact or {})
    if not message_id or sender is None:
        # Used to be a bare `return []`. A message we cannot attribute is a
        # customer writing into silence, and the only class of inbound failure
        # left that said nothing at all -- so it says something now, including
        # which fields did arrive, since the shape of these payloads is changing
        # under us as Meta rolls usernames out.
        logger.error(
            "Could not tell who sent WhatsApp message %s; message keys=%s contact keys=%s",
            message_id,
            sorted(message),
            sorted(contact or {}),
        )
        events.emit(
            type=events.SEND_FAILED,
            tool="whatsapp.receive",
            tool_use_id=str(message_id or ""),
            output="could not identify the sender: no phone number and no user id",
            status="error",
        )
        return []

    # A tool that produces a file cannot send it: this function is the one place
    # that decides what goes out, and the gateway path below returns payloads
    # rather than sending them. So a tool leaves the file here and it travels
    # with the reply. Opened per message, so nothing can leak into the next one.
    outbox.begin()
    # And the same again for something a tool wants said a minute from now, when
    # there is no reply left to put it in. Opened here rather than in
    # `_handle_text_message` so that a tool can tell, from anywhere in the turn,
    # whether this conversation is one that can be followed up at all.
    notify.begin()

    if session_store.is_duplicate_message(message_id):
        logger.info("Skipping duplicate WhatsApp message %s", message_id)
        return []

    if not session_store.check_and_increment_daily_count(sender.key):
        logger.info("Rate limit hit for %s", sender.key)
        return _canned(sender, RATE_LIMIT_MESSAGE)

    msg_type = message.get("type")
    if msg_type == "interactive":
        return _handle_interactive_reply(sender, message.get("interactive", {}))

    if msg_type == "audio":
        spoken = _transcribe_voice_note(message.get("audio") or {})
        if not spoken:
            return _canned(sender, VOICE_UNREADABLE_MESSAGE)
        # From here it is a text message and nothing downstream is told otherwise:
        # "menu" said out loud resets the demo, a spoken product name searches the
        # ERP, and the history the model reads holds the words, not the audio.
        return _handle_text_message(sender, spoken, source=audit.VOICE)

    if msg_type == "image":
        block = message.get("image") or {}
        photo = _fetch_photo(block)
        if photo is None:
            return _canned(sender, IMAGE_UNREADABLE_MESSAGE)
        # The picture travels beside the turn, not inside it: what the history
        # keeps is the caption under a marker, which is all the model can use on
        # a later turn anyway.
        return _handle_text_message(
            sender,
            _photo_text(str(block.get("caption") or "")),
            source=audit.IMAGE,
            image=photo,
        )

    if msg_type == "document":
        block = message.get("document") or {}
        document = _fetch_document(block)
        if document is None:
            return _canned(sender, DOCUMENT_UNREADABLE_MESSAGE)
        # Filed before the turn runs, because this is not a one-turn attachment:
        # every message from here on hangs it back on the line below until the
        # customer sends another file or starts the demo over.
        doc_store.remember(sender.key, document)
        return _handle_text_message(sender, document.marker, source=audit.DOCUMENT)

    if msg_type != "text":
        logger.info("Ignoring unsupported message type '%s' from %s", msg_type, sender.key)
        return _canned(sender, UNSUPPORTED_TYPE_MESSAGE)

    text = message.get("text", {}).get("body", "")
    return _handle_text_message(sender, text)


def _transcribe_voice_note(audio: dict) -> str:
    """What the customer said, or "" if we could not tell.

    The console line this leaves behind is the point of the feature as much as the
    reply is: the customer hears nothing happen, while the room watching the
    second screen sees the sentence the bot heard before it acts on it.
    """
    media_id = audio.get("id")
    if not media_id:
        logger.error("Audio message arrived with no media id: keys=%s", sorted(audio))
        events.emit(
            type=events.SEND_FAILED,
            tool=VOICE_TOOL,
            tool_use_id="",
            output="audio message carried no media id",
            status="error",
        )
        return ""

    events.emit(
        type=events.TOOL_START,
        tool=VOICE_TOOL,
        tool_use_id=media_id,
        input={"mime_type": audio.get("mime_type", "")},
    )
    started = time.monotonic()
    try:
        media = whatsapp_media.fetch_media(media_id)
        spoken = transcribe.transcribe(media.content, media.mime_type)
    except (whatsapp_media.MediaError, transcribe.TranscriptionError) as failure:
        logger.exception("Could not transcribe voice note %s", media_id)
        events.emit(
            type=events.TOOL_END,
            tool=VOICE_TOOL,
            tool_use_id=media_id,
            output=f"{type(failure).__name__}: {failure}",
            duration_ms=int((time.monotonic() - started) * 1000),
            status="error",
        )
        return ""

    events.emit(
        type=events.TOOL_END,
        tool=VOICE_TOOL,
        tool_use_id=media_id,
        # An empty transcript is a successful call that heard nothing, and on a
        # screen a blank line reads as a bug rather than as silence.
        output=(spoken or NOTHING_AUDIBLE)[: llm.MAX_CONSOLE_OUTPUT_CHARS],
        duration_ms=int((time.monotonic() - started) * 1000),
        status="ok",
    )
    return spoken


def _photo_text(caption: str) -> str:
    """A photo as the line that stands in for it in the transcript.

    One string doing both jobs, so there is no branch: it is the text block sent
    alongside the picture this turn, and it is what stays in the history once the
    picture is gone. The marker also keeps a photo captioned "menu" from resetting
    the demo -- `MENU_KEYWORDS` matches the whole message and this is never one.
    """
    return f"{PHOTO_MARKER} {caption}".strip() if caption.strip() else PHOTO_MARKER


def _fetch_photo(image: dict) -> llm.Image | None:
    """The picture the customer sent, or None if we cannot put it before the model.

    The console line is half the point, as with a voice note: the customer sees
    only a pause, while the room watching the second screen sees the file arrive
    with its type and size before anything is said about it.
    """
    media_id = image.get("id")
    if not media_id:
        logger.error("Image message arrived with no media id: keys=%s", sorted(image))
        events.emit(
            type=events.SEND_FAILED,
            tool=IMAGE_TOOL,
            tool_use_id="",
            output="image message carried no media id",
            status="error",
        )
        return None

    events.emit(
        type=events.TOOL_START,
        tool=IMAGE_TOOL,
        tool_use_id=media_id,
        input={"mime_type": image.get("mime_type", "")},
    )
    started = time.monotonic()
    try:
        media = whatsapp_media.fetch_media(media_id)
    except whatsapp_media.MediaError as failure:
        logger.exception("Could not download image %s", media_id)
        _end_image_span(media_id, started, f"{type(failure).__name__}: {failure}", "error")
        return None

    # Checked after the download rather than off the webhook's `mime_type`,
    # because the type Meta reports on the metadata hop is the one the bytes
    # actually came with -- and the model is the party that gets to refuse.
    media_type = llm.image_media_type(media.mime_type)
    if not media_type:
        logger.error("Image %s is of unreadable type '%s'", media_id, media.mime_type)
        _end_image_span(
            media_id, started, f"cannot read an image of type '{media.mime_type}'", "error"
        )
        return None

    _end_image_span(media_id, started, f"{media_type}, {len(media.content)} bytes", "ok")
    return llm.Image(data=media.content, media_type=media_type)


def _document_text(filename: str, caption: str) -> str:
    """A file as the line that stands in for it in the transcript.

    The filename is in it because this line has a second job the photo marker
    does not have: it is what the PDF is hung back on every turn afterwards, so
    two different files cannot share it. It also reads as what happened -- "the
    customer sent price-list.pdf" -- to anyone reading the transcript later.
    """
    return " ".join(part for part in (DOCUMENT_MARKER, filename, caption.strip()) if part)


def _fetch_document(document: dict) -> llm.Document | None:
    """The file the customer sent, or None if we cannot put it before the model.

    Held to its own size cap rather than the photo's: see
    `settings.whatsapp_document_max_bytes`.
    """
    media_id = document.get("id")
    if not media_id:
        logger.error("Document message arrived with no media id: keys=%s", sorted(document))
        events.emit(
            type=events.SEND_FAILED,
            tool=DOCUMENT_TOOL,
            tool_use_id="",
            output="document message carried no media id",
            status="error",
        )
        return None

    filename = str(document.get("filename") or "").strip()
    events.emit(
        type=events.TOOL_START,
        tool=DOCUMENT_TOOL,
        tool_use_id=media_id,
        input={"mime_type": document.get("mime_type", ""), "filename": filename},
    )
    started = time.monotonic()
    try:
        media = whatsapp_media.fetch_media(
            media_id, max_bytes=settings.whatsapp_document_max_bytes
        )
    except whatsapp_media.MediaError as failure:
        logger.exception("Could not download document %s", media_id)
        _end_document_span(media_id, started, f"{type(failure).__name__}: {failure}", "error")
        return None

    # After the download, for the same reason a photo's type is: what Meta put on
    # the webhook and what the bytes actually are can differ, and the second one
    # is what the API answers to.
    if not llm.document_media_type(media.mime_type):
        logger.error("Document %s is of unreadable type '%s'", media_id, media.mime_type)
        _end_document_span(
            media_id, started, f"cannot read a document of type '{media.mime_type}'", "error"
        )
        return None

    # A file Meta sent us with no name still has to be called something: the
    # citations under the reply are labelled with it.
    filename = filename or f"{media_id}.pdf"
    _end_document_span(media_id, started, f"{filename}, {len(media.content)} bytes", "ok")
    return llm.Document(
        data=media.content,
        filename=filename,
        marker=_document_text(filename, str(document.get("caption") or "")),
    )


def _end_document_span(media_id: str, started: float, output: str, status: str) -> None:
    events.emit(
        type=events.TOOL_END,
        tool=DOCUMENT_TOOL,
        tool_use_id=media_id,
        output=output[: llm.MAX_CONSOLE_OUTPUT_CHARS],
        duration_ms=int((time.monotonic() - started) * 1000),
        status=status,
    )


def _end_image_span(media_id: str, started: float, output: str, status: str) -> None:
    events.emit(
        type=events.TOOL_END,
        tool=IMAGE_TOOL,
        tool_use_id=media_id,
        output=output[: llm.MAX_CONSOLE_OUTPUT_CHARS],
        duration_ms=int((time.monotonic() - started) * 1000),
        status=status,
    )


def _start_over(sender: Sender) -> None:
    """Put this customer back at the demo menu, without forgetting them.

    The conversation goes; the customer record stays, which is the whole
    difference between "menu" and never having written in. Nothing is stored for
    someone we have never seen, so a stranger who opens with "menu" still leaves
    no record behind.
    """
    # Not part of the record, so it has to be dropped by name. A fresh demo that
    # could still quote the last one's PDF is not a fresh demo.
    doc_store.forget(sender.key)
    profile = user_store.get(sender.key)
    if profile is None:
        return
    profile.bot_id = None
    profile.history.clear()
    # Whatever they pick next is a new transcript.
    profile.conversation_id = None
    # And whoever was holding it does not hold the next one. Without this a
    # customer who typed `menu` while a person had them would be shown the demo
    # list and then met with silence for every message after it, because the
    # flag outlived the conversation it belonged to.
    handover.end(profile)
    user_store.save(profile)


def _remember_identity(profile, sender: Sender) -> None:
    """Bring the record level with what this message just told us.

    A username is filled in as the display name only where we have nothing
    better. It is what a customer with no phone number is called, and being
    greeted by their own handle is the difference between being recognised and
    being addressed as nobody -- but a name they gave us in conversation
    outranks a handle they may change tomorrow.
    """
    profile.phone = sender.phone or profile.phone
    profile.user_id = sender.user_id or profile.user_id
    profile.username = sender.username or profile.username
    if not profile.display_name and sender.username:
        profile.display_name = sender.username


def _canned(sender: "Sender", message: str) -> list[dict]:
    """One of the bot's own apologies -- unless a person has the conversation.

    Every one of these sits on a path that returns before `_handle_text_message`
    and therefore before the handover check inside it: a sticker, a voice note
    that would not transcribe, a photo that would not download, the daily cap.
    A cold review found all five, and they are the worst possible thing for the
    bot to say while somebody is typing, because they are the sentences that
    announce there is a bot. "This demo can only read text, voice, photo and
    PDF" arriving in the middle of a human conversation is the join made visible
    in one line.
    """
    if handover.active(user_store.get(sender.key)):
        logger.info("swallowing a canned reply to %s: a person has it", sender.key)
        return []
    return [whatsapp.build_text_message(sender.key, message)]


def _asked_for_a_person(text: str) -> bool:
    """Whether the customer has asked to stop talking to a machine.

    Matched as a phrase inside the message rather than as the whole of it, unlike
    `menu`: nobody types this on its own, they type "can I speak to a human
    please". Which is also why the list holds phrases and not words -- see
    `HUMAN_PHRASES` for the three ordinary sentences the word version muted the
    bot on, one of them the likeliest question at an AI demo.
    """
    said = " ".join(text.lower().split())
    return any(phrase in said for phrase in HUMAN_PHRASES)


def _record_while_silent(profile, text: str, source: str, reply: str = "") -> None:
    """File a turn the bot is not answering.

    The transcript has to be whole whoever was typing -- it is the thing the
    console reads back and the thing the model is replayed when it gets the
    conversation back. A customer who explained their problem to a person and
    then finds the bot has never heard of it has been handed back badly.
    """
    audit.begin_for(profile, audit.WHATSAPP)
    try:
        profile.add_message("user", text)
        audit.record_message("user", text, source)
        if reply:
            profile.add_message("assistant", reply)
            audit.record_message("assistant", reply)
        user_store.save(profile)
    finally:
        audit.close()


def _handle_text_message(
    sender: Sender,
    text: str,
    source: str = audit.TEXT,
    image: llm.Image | None = None,
) -> list[dict]:
    if text.strip().lower() in MENU_KEYWORDS:
        logger.info("Menu reset requested by %s", sender.key)
        _start_over(sender)
        return _send_bot_list(sender.key)

    profile = user_store.get_or_create(sender.key)
    _remember_identity(profile, sender)

    if handover.active(profile):
        # A person has this conversation. The message is filed so the transcript
        # is whole and so the bot has read it when it gets the conversation back,
        # and then nothing is sent: whoever is typing on the console is the only
        # voice the customer hears until they hand it over.
        _record_while_silent(profile, text, source)
        logger.info("%s is in a person's hands; the bot stays quiet", sender.key)
        return []

    if _asked_for_a_person(text):
        logger.info("%s asked for a person", sender.key)
        handover.begin(profile, reason=text.strip()[:200])
        _record_while_silent(profile, text, source, reply=handover.HANDED_OVER_MESSAGE)
        return [whatsapp.build_text_message(sender.key, handover.HANDED_OVER_MESSAGE)]

    if profile.bot_id is None:
        logger.info("No bot selected yet for %s, showing bot list", sender.key)
        return _send_bot_list(sender.key)

    bot = get_bot(profile.bot_id)
    if not bot:
        # A demo that was retired between one message and the next.
        _start_over(sender)
        return _send_bot_list(sender.key)

    # Opened around the whole exchange, not just the writes: the tool calls the
    # model makes in between are recorded off this same turn, and outside one
    # they would have no conversation to belong to.
    audit.begin_for(profile, audit.WHATSAPP)
    try:
        profile.add_message("user", text)
        # Recorded before the reply is attempted, and kept even if that reply
        # then fails to build. What the customer said is a fact regardless of
        # whether we managed to answer it -- and a turn that produced nothing is
        # precisely the kind a transcript is opened to explain.
        audit.record_message("user", text, source)
        # Whatever file this customer last sent, on every turn until they send
        # another -- `llm` hangs it back on the line it arrived as, and drops it
        # once that line has rolled out of the history window.
        reply = llm.get_reply(
            bot, profile, profile.history, image=image, document=doc_store.get(sender.key)
        )
        # A turn takes seconds and several tool calls, and the moment somebody
        # reaches for the console is the moment the bot is visibly struggling --
        # so a person taking over WHILE this ran is the likely case, not the
        # exotic one. Re-read rather than trusted from the copy loaded before the
        # model was called: this object has been in hand the whole time and knows
        # nothing about it. Found by a cold review of task 20.
        taken = user_store.get(sender.key)
        if handover.active(taken):
            logger.info("dropping the bot's answer to %s: a person took over mid-turn", sender.key)
            # The flag is carried onto the copy about to be saved, or this save
            # is the lost update all over again -- this object was loaded before
            # the console was clicked and has a zero where the truth is.
            profile.handover_since = taken.handover_since
            # What the customer said is kept; the answer nobody sent is not. The
            # colleague picking this up needs to read the question, and the model
            # must not be replayed a reply that never left the building.
            user_store.save(profile)
            return []
        # Built before it is recorded, deliberately. A reply WhatsApp will not carry
        # must not become part of this customer's history either: the turn is
        # dropped whole and the next message starts from the last good exchange,
        # rather than from one the model cannot be shown again.
        # Anything a tool produced goes out after the words explaining it.
        payloads = [whatsapp.build_text_message(sender.key, reply), *outbox.drain(sender.key)]
        # What the model wrote, without the page footnote rendered under it --
        # see `llm.without_sources`. The audit log below keeps the whole
        # thing, because that is what the customer was sent.
        profile.add_message("assistant", llm.without_sources(reply))
        audit.record_message("assistant", reply)
        # Saved after the reply, so the exchange survives a restart and is still
        # there when they write again days later - this is what "the bot remembers
        # me" is actually made of.
        user_store.save(profile)
    finally:
        audit.close()
    # After the turn, because this is where the recipient is known -- a tool
    # queues a follow-up without ever learning who it is for. The clock starts
    # now; the reply itself goes out a moment later, from the caller.
    notify.dispatch(sender.key)
    logger.info("Sending LLM reply to %s for bot=%s", sender.key, bot.id)
    return payloads


def _handle_interactive_reply(sender: Sender, interactive: dict) -> list[dict]:
    reply_type = interactive.get("type")
    if reply_type == "list_reply":
        selected = interactive.get("list_reply", {})
    elif reply_type == "button_reply":
        selected = interactive.get("button_reply", {})
    else:
        return []
    selected_id = selected.get("id")
    if not selected_id:
        return []

    profile = user_store.get_or_create(sender.key)
    _remember_identity(profile, sender)

    if profile.bot_id is None:
        bot = get_bot(selected_id)
        if not bot:
            return _send_bot_list(sender.key)
        profile.bot_id = bot.id
        # A new run of a demo is a new transcript.
        profile.conversation_id = audit.new_conversation_id()
        # Picking a demo off the menu is deliberate enough to file the record on;
        # the greeting that follows has to still be there on the next message.
        user_store.save(profile)
        logger.info("%s selected bot %s", sender.key, bot.id)
        audit.begin_for(profile, audit.WHATSAPP)
        try:
            return _start_conversation(sender.key, bot)
        finally:
            audit.close()

    said = _resolve_quick_question(profile.bot_id, selected_id) or _resolve_product_choice(
        selected_id, str(selected.get("title") or "")
    )
    return _handle_text_message(sender, said, source=audit.INTERACTIVE) if said else []


def _resolve_product_choice(row_id: str, title: str) -> str | None:
    """A tapped product, as the sentence the customer would have typed.

    Taking the same path as a typed message is the point: the model reads it in
    the conversation it is already having, so a tap can be answered with "how
    many?" or "what's the address?" like any other way of asking for something.

    The sku_id comes along because it is the one thing the tap knows and the
    words do not -- it saves a second search, and more importantly it names the
    exact row, where two products can easily share the first 24 characters of
    their name. The title is echoed back to us by WhatsApp from the row we sent.
    """
    if not row_id.startswith(erp.PRODUCT_ROW_PREFIX):
        return None
    sku_id = row_id.removeprefix(erp.PRODUCT_ROW_PREFIX)
    named = f" ({title})" if title else ""
    return f"I'd like to order the product with ERP sku_id {sku_id}{named}."


def _resolve_quick_question(bot_id: str, button_id: str) -> str | None:
    if not button_id.startswith("qq:"):
        return None
    try:
        index = int(button_id.removeprefix("qq:"))
    except ValueError:
        return None
    bot = get_bot(bot_id)
    if not bot or index >= len(bot.quick_questions):
        return None
    return bot.quick_questions[index].en


def _start_conversation(to: str, bot: BotConfig) -> list[dict]:
    greeting = f"{bot.disclaimer.en}\n\n{GREETING_SUFFIX_EN}"
    # The greeting is the first thing the customer reads, so a transcript that
    # skipped it would open mid-conversation. A no-op outside a turn, which is
    # what makes it safe to put here rather than at every call site.
    audit.record_message("assistant", greeting)
    payloads = [whatsapp.build_text_message(to, greeting)]
    if bot.quick_questions:
        buttons = [{"id": f"qq:{i}", "title": q.en} for i, q in enumerate(bot.quick_questions[:3])]
        payloads.append(
            whatsapp.build_quick_reply_buttons(to, "Quick questions to get you started:", buttons)
        )
    return payloads


def _send_bot_list(to: str) -> list[dict]:
    rows = [whatsapp.list_row(bot.id, bot.name.en, bot.description.en) for bot in list_bots()]
    return [
        whatsapp.build_interactive_list(
            to,
            body_text="Welcome! Which type of AI assistant would you like to try?",
            button_text="Select",
            sections=[{"title": "Demo types", "rows": rows}],
            header_text="AI Chatbot Demo",
        )
    ]
