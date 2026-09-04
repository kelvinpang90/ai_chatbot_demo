from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.bots.registry import BotConfig, get_bot, list_bots
from app.config import settings
from app.console import events
from app.services import llm, outbox, whatsapp
from app.services.user_store import user_store
from app.session_store import session_store

router = APIRouter(prefix="/webhook/whatsapp")
logger = logging.getLogger(__name__)

RATE_LIMIT_MESSAGE = "You've reached today's message limit for this demo. Please try again tomorrow."
UNSUPPORTED_TYPE_MESSAGE = (
    "Sorry, I can only read text messages in this demo - please type your question instead."
)
GREETING_SUFFIX_EN = "How can I help you today?"
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

    if msg_type != "text":
        logger.info("Ignoring unsupported message type '%s' from %s", msg_type, sender.key)
        return [whatsapp.build_text_message(sender.key, UNSUPPORTED_TYPE_MESSAGE)]

    text = message.get("text", {}).get("body", "")
    return _handle_text_message(sender, text)


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


def _handle_text_message(sender: Sender, text: str) -> list[dict]:
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

    profile.add_message("user", text)
    reply = llm.get_reply(bot, profile, profile.history)
    # Built before it is recorded, deliberately. A reply WhatsApp will not carry
    # must not become part of this customer's history either: the turn is
    # dropped whole and the next message starts from the last good exchange,
    # rather than from one the model cannot be shown again.
    # Anything a tool produced goes out after the words explaining it.
    payloads = [whatsapp.build_text_message(sender.key, reply), *outbox.drain(sender.key)]
    profile.add_message("assistant", reply)
    # Saved after the reply, so the exchange survives a restart and is still
    # there when they write again days later - this is what "the bot remembers
    # me" is actually made of.
    user_store.save(profile)
    logger.info("Sending LLM reply to %s for bot=%s", sender.key, bot.id)
    return payloads


def _handle_interactive_reply(sender: Sender, interactive: dict) -> list[dict]:
    reply_type = interactive.get("type")
    if reply_type == "list_reply":
        selected_id = interactive.get("list_reply", {}).get("id")
    elif reply_type == "button_reply":
        selected_id = interactive.get("button_reply", {}).get("id")
    else:
        return []
    if not selected_id:
        return []

    profile = user_store.get_or_create(sender.key)
    _remember_identity(profile, sender)

    if profile.bot_id is None:
        bot = get_bot(selected_id)
        if not bot:
            return _send_bot_list(sender.key)
        profile.bot_id = bot.id
        # Picking a demo off the menu is deliberate enough to file the record on;
        # the greeting that follows has to still be there on the next message.
        user_store.save(profile)
        logger.info("%s selected bot %s", sender.key, bot.id)
        return _start_conversation(sender.key, bot)

    question = _resolve_quick_question(profile.bot_id, selected_id)
    return _handle_text_message(sender, question) if question else []


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
    payloads = [whatsapp.build_text_message(to, greeting)]
    if bot.quick_questions:
        buttons = [
            {"id": f"qq:{i}", "title": _truncate(q.en, 20)}
            for i, q in enumerate(bot.quick_questions[:3])
        ]
        payloads.append(
            whatsapp.build_quick_reply_buttons(to, "Quick questions to get you started:", buttons)
        )
    return payloads


def _send_bot_list(to: str) -> list[dict]:
    rows = [
        {"id": bot.id, "title": _truncate(bot.name.en, 24), "description": _truncate(bot.description.en, 72)}
        for bot in list_bots()
    ]
    return [
        whatsapp.build_interactive_list(
            to,
            body_text="Welcome! Which type of AI assistant would you like to try?",
            button_text="Select",
            sections=[{"title": "Demo types", "rows": rows}],
            header_text="AI Chatbot Demo",
        )
    ]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
