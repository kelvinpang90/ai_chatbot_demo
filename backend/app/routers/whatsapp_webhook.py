from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.bots.registry import BotConfig, get_bot, get_identity, list_bots
from app.config import settings
from app.services import llm, outbox, whatsapp
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
    for message in _extract_messages(payload):
        background_tasks.add_task(_handle_incoming_message, message)

    return Response(status_code=200)


def _extract_messages(payload: dict) -> list[dict]:
    messages: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages.extend(value.get("messages", []))
    return messages


def _handle_incoming_message(message: dict) -> None:
    try:
        for payload in dispatch_message(message):
            whatsapp.send_raw(payload)
    except Exception:
        logger.exception("Unhandled error processing WhatsApp message %s", message.get("id"))


def dispatch_message(message: dict) -> list[dict]:
    """Process one raw Meta message object and return the reply payload(s) to send.

    Shared by the public Meta-facing webhook above and the internal
    /internal/whatsapp/inbound endpoint (see routers/internal_whatsapp.py) used by
    whatsapp_gateway, so this never calls whatsapp.send_* directly.
    """
    message_id = message.get("id")
    phone = message.get("from")
    if not message_id or not phone:
        return []

    # A tool that produces a file cannot send it: this function is the one place
    # that decides what goes out, and the gateway path below returns payloads
    # rather than sending them. So a tool leaves the file here and it travels
    # with the reply. Opened per message, so nothing can leak into the next one.
    outbox.begin()

    if session_store.is_duplicate_message(message_id):
        logger.info("Skipping duplicate WhatsApp message %s", message_id)
        return []

    if not session_store.check_and_increment_daily_count(phone):
        logger.info("Rate limit hit for %s", phone)
        return [whatsapp.build_text_message(phone, RATE_LIMIT_MESSAGE)]

    msg_type = message.get("type")
    if msg_type == "interactive":
        return _handle_interactive_reply(phone, message.get("interactive", {}))

    if msg_type != "text":
        logger.info("Ignoring unsupported message type '%s' from %s", msg_type, phone)
        return [whatsapp.build_text_message(phone, UNSUPPORTED_TYPE_MESSAGE)]

    text = message.get("text", {}).get("body", "")
    return _handle_text_message(phone, text)


def _handle_text_message(phone: str, text: str) -> list[dict]:
    if text.strip().lower() in MENU_KEYWORDS:
        logger.info("Menu reset requested by %s", phone)
        session_store.reset(phone)
        return _send_bot_list(phone)

    session = session_store.get_or_create(phone)

    if session.bot_id is None:
        logger.info("No bot selected yet for %s, showing bot list", phone)
        return _send_bot_list(phone)

    if session.identity_id is None:
        bot = get_bot(session.bot_id)
        if not bot:
            return []
        logger.info("No identity selected yet for %s, showing identity list", phone)
        return _send_identity_list(phone, bot)

    bot = get_bot(session.bot_id)
    identity = get_identity(session.bot_id, session.identity_id)
    if not bot or not identity:
        session_store.reset(phone)
        return _send_bot_list(phone)

    session.add_message("user", text)
    reply = llm.get_reply(bot, identity, session.history)
    session.add_message("assistant", reply)
    logger.info("Sending LLM reply to %s for bot=%s", phone, bot.id)
    # Anything a tool produced goes out after the words explaining it.
    return [whatsapp.build_text_message(phone, reply), *outbox.drain(phone)]


def _handle_interactive_reply(phone: str, interactive: dict) -> list[dict]:
    reply_type = interactive.get("type")
    if reply_type == "list_reply":
        selected_id = interactive.get("list_reply", {}).get("id")
    elif reply_type == "button_reply":
        selected_id = interactive.get("button_reply", {}).get("id")
    else:
        return []
    if not selected_id:
        return []

    session = session_store.get_or_create(phone)

    if session.bot_id is None:
        bot = get_bot(selected_id)
        if not bot:
            return _send_bot_list(phone)
        session.bot_id = bot.id
        logger.info("%s selected bot %s", phone, bot.id)
        return _send_identity_list(phone, bot)

    if session.identity_id is None:
        identity = get_identity(session.bot_id, selected_id)
        if not identity:
            bot = get_bot(session.bot_id)
            return _send_identity_list(phone, bot) if bot else []
        session.identity_id = identity.id
        logger.info("%s selected identity %s for bot %s", phone, identity.id, session.bot_id)
        bot = get_bot(session.bot_id)
        return _start_conversation(phone, bot) if bot else []

    question = _resolve_quick_question(session.bot_id, selected_id)
    return _handle_text_message(phone, question) if question else []


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


def _start_conversation(phone: str, bot: BotConfig) -> list[dict]:
    greeting = f"{bot.disclaimer.en}\n\n{GREETING_SUFFIX_EN}"
    payloads = [whatsapp.build_text_message(phone, greeting)]
    if bot.quick_questions:
        buttons = [
            {"id": f"qq:{i}", "title": _truncate(q.en, 20)}
            for i, q in enumerate(bot.quick_questions[:3])
        ]
        payloads.append(
            whatsapp.build_quick_reply_buttons(phone, "Quick questions to get you started:", buttons)
        )
    return payloads


def _send_bot_list(phone: str) -> list[dict]:
    rows = [
        {"id": bot.id, "title": _truncate(bot.name.en, 24), "description": _truncate(bot.description.en, 72)}
        for bot in list_bots()
    ]
    return [
        whatsapp.build_interactive_list(
            phone,
            body_text="Welcome! Which type of AI assistant would you like to try?",
            button_text="Select",
            sections=[{"title": "Demo types", "rows": rows}],
            header_text="AI Chatbot Demo",
        )
    ]


def _send_identity_list(phone: str, bot: BotConfig) -> list[dict]:
    rows = [
        {"id": identity.id, "title": _truncate(identity.label.en, 24), "description": _truncate(identity.label.en, 72)}
        for identity in bot.identities
    ]
    return [
        whatsapp.build_interactive_list(
            phone,
            body_text=f"Great choice! Who would you like to be for this {bot.name.en} demo?",
            button_text="Select",
            sections=[{"title": "Demo identities", "rows": rows}],
        )
    ]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
