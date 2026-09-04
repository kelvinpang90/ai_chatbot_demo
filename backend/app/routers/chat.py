from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException

from app.bots.registry import LocalizedText, get_bot, list_bots
from app.config import settings
from app.models import (
    BotDetail,
    BotSummary,
    LoginRequest,
    LoginResponse,
    ResetResponse,
    SelectBotRequest,
    SelectBotResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import llm
from app.session_store import session_store

router = APIRouter(prefix="/api")

# Demo-scale: valid tokens live in memory, same single-process constraint as session_store.
_valid_tokens: set[str] = set()

GREETING_SUFFIX = {
    "zh": "有什么可以帮你的吗？",
    "en": "How can I help you today?",
    "ms": "Bagaimana saya boleh bantu anda hari ini?",
}


def _localize(text: LocalizedText, lang: str) -> str:
    return getattr(text, lang, None) or text.en


def require_auth(x_access_token: str | None = Header(default=None)) -> None:
    if not x_access_token or x_access_token not in _valid_tokens:
        raise HTTPException(status_code=401, detail="Invalid or missing access token")


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    if not settings.demo_access_password or body.password != settings.demo_access_password:
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = secrets.token_urlsafe(24)
    _valid_tokens.add(token)
    return LoginResponse(token=token)


@router.get("/bots", response_model=list[BotSummary], dependencies=[Depends(require_auth)])
def list_bots_endpoint(lang: str = "en") -> list[BotSummary]:
    return [
        BotSummary(
            id=bot.id,
            name=_localize(bot.name, lang),
            description=_localize(bot.description, lang),
            icon=bot.icon,
        )
        for bot in list_bots()
    ]


@router.get("/bots/{bot_id}", response_model=BotDetail, dependencies=[Depends(require_auth)])
def get_bot_endpoint(bot_id: str, lang: str = "en") -> BotDetail:
    bot = get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return BotDetail(
        id=bot.id,
        name=_localize(bot.name, lang),
        description=_localize(bot.description, lang),
        icon=bot.icon,
    )


@router.post(
    "/chat/{session_id}/select",
    response_model=SelectBotResponse,
    dependencies=[Depends(require_auth)],
)
def select_bot(session_id: str, body: SelectBotRequest) -> SelectBotResponse:
    bot = get_bot(body.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    session = session_store.get_or_create(session_id)
    session.reset()
    session.bot_id = bot.id

    disclaimer = _localize(bot.disclaimer, body.lang)
    suffix = GREETING_SUFFIX.get(body.lang, GREETING_SUFFIX["en"])
    greeting = f"{disclaimer}\n\n{suffix}"
    quick_questions = [_localize(q, body.lang) for q in bot.quick_questions]
    return SelectBotResponse(greeting=greeting, quick_questions=quick_questions)


@router.post(
    "/chat/{session_id}/message",
    response_model=SendMessageResponse,
    dependencies=[Depends(require_auth)],
)
def send_message(session_id: str, body: SendMessageRequest) -> SendMessageResponse:
    session = session_store.get(session_id)
    if not session or not session.bot_id:
        raise HTTPException(status_code=409, detail="Session has no bot selected yet")

    bot = get_bot(session.bot_id)
    if not bot:
        raise HTTPException(status_code=409, detail="Session's bot no longer exists")

    session.add_message("user", body.message)
    # No customer record: a web visitor has no phone number to key one on until
    # task 33 asks them for it. WhatsApp is where identity lives today.
    reply = llm.get_reply(bot, None, session.history)
    session.add_message("assistant", reply)

    return SendMessageResponse(reply=reply)


@router.post(
    "/chat/{session_id}/reset",
    response_model=ResetResponse,
    dependencies=[Depends(require_auth)],
)
def reset_session(session_id: str) -> ResetResponse:
    session_store.reset(session_id)
    return ResetResponse(status="ok")
