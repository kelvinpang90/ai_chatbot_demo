from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.bots.registry import BotConfig, get_bot, list_bots
from app.config import settings
from app.console import events
from app.services import audit, llm, outbox, transcribe, whatsapp, whatsapp_media
from app.services.user_store import user_store
from app.session_store import session_store
from app.tools import erp

router = APIRouter(prefix="/webhook/whatsapp")
logger = logging.getLogger(__name__)

RATE_LIMIT_MESSAGE = "You've reached today's message limit for this demo. Please try again tomorrow."
UNSUPPORTED_TYPE_MESSAGE = (
    "Sorry, I can only read text, voice and photo messages in this demo - "
    "please type your question instead."
)
# One line for both ways a voice note can come to nothing, because the customer's
# next move is the same either way. Which of the two it was is on the console.
VOICE_UNREADABLE_MESSAGE = (
    "Sorry, I couldn't make out that voice message - please type your question instead."
)
# Same posture for a photo. Three ways it can come to nothing -- the download
# failed, the file was over the cap, or it is a format the model cannot read --
# and one thing left for the customer to do about any of them.
IMAGE_UNREADABLE_MESSAGE = (
    "Sorry, I couldn't open that photo - please try sending it again, "
    "or describe what you're seeing."
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
MENU_KEYWORDS = {"menu", "菜单"}


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

    if session_store.is_duplicate_message(message_id):
        logger.info("Skipping duplicate WhatsApp message %s", message_id)
        return []

    if not session_store.check_and_increment_daily_count(sender.key):
        logger.info("Rate limit hit for %s", sender.key)
        return [whatsapp.build_text_message(sender.key, RATE_LIMIT_MESSAGE)]

    msg_type = message.get("type")
    if msg_type == "interactive":
        return _handle_interactive_reply(sender, message.get("interactive", {}))

    if msg_type == "audio":
        spoken = _transcribe_voice_note(message.get("audio") or {})
        if not spoken:
            return [whatsapp.build_text_message(sender.key, VOICE_UNREADABLE_MESSAGE)]
        # From here it is a text message and nothing downstream is told otherwise:
        # "menu" said out loud resets the demo, a spoken product name searches the
        # ERP, and the history the model reads holds the words, not the audio.
        return _handle_text_message(sender, spoken, source=audit.VOICE)

    if msg_type == "image":
        block = message.get("image") or {}
        photo = _fetch_photo(block)
        if photo is None:
            return [whatsapp.build_text_message(sender.key, IMAGE_UNREADABLE_MESSAGE)]
        # The picture travels beside the turn, not inside it: what the history
        # keeps is the caption under a marker, which is all the model can use on
        # a later turn anyway.
        return _handle_text_message(
            sender,
            _photo_text(str(block.get("caption") or "")),
            source=audit.IMAGE,
            image=photo,
        )

    if msg_type != "text":
        logger.info("Ignoring unsupported message type '%s' from %s", msg_type, sender.key)
        return [whatsapp.build_text_message(sender.key, UNSUPPORTED_TYPE_MESSAGE)]

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
    profile = user_store.get(sender.key)
    if profile is None:
        return
    profile.bot_id = None
    profile.history.clear()
    # Whatever they pick next is a new transcript.
    profile.conversation_id = None
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
        reply = llm.get_reply(bot, profile, profile.history, image=image)
        # Built before it is recorded, deliberately. A reply WhatsApp will not carry
        # must not become part of this customer's history either: the turn is
        # dropped whole and the next message starts from the last good exchange,
        # rather than from one the model cannot be shown again.
        # Anything a tool produced goes out after the words explaining it.
        payloads = [whatsapp.build_text_message(sender.key, reply), *outbox.drain(sender.key)]
        profile.add_message("assistant", reply)
        audit.record_message("assistant", reply)
        # Saved after the reply, so the exchange survives a restart and is still
        # there when they write again days later - this is what "the bot remembers
        # me" is actually made of.
        user_store.save(profile)
    finally:
        audit.close()
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
