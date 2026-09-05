from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.bots.registry import BotConfig, LocalizedText, get_bot, list_bots
from app.models import (
    BotDetail,
    BotSummary,
    ChatTurn,
    IdentifyRequest,
    IdentifyResponse,
    ResetResponse,
    SelectBotRequest,
    SelectBotResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.services import llm, phone
from app.services.user_store import UserProfile, identity, user_store

# 2026-09-05: the access password is gone at the owner's request, so these
# routes are open. Whoever has the link can run the demo -- which is what "show
# a customer the link" was already worth in practice.
router = APIRouter(prefix="/api")

GREETING_SUFFIX = {
    "zh": "有什么可以帮你的吗？",
    "en": "How can I help you today?",
    "ms": "Bagaimana saya boleh bantu anda hari ini?",
}


def _localize(text: LocalizedText, lang: str) -> str:
    return getattr(text, lang, None) or text.en


def _detail(bot: BotConfig, lang: str) -> BotDetail:
    return BotDetail(
        id=bot.id,
        name=_localize(bot.name, lang),
        description=_localize(bot.description, lang),
        icon=bot.icon,
    )


def _identity_or_400(key: str) -> str:
    """The key this request is about, refusing anything unfilable.

    The key comes back to us from /identify, which already normalised it, but it
    arrives in a URL and so is checked again rather than trusted: a key nothing
    can be filed under is the one case that would put two visitors in one record.
    """
    try:
        return identity(key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a usable phone number") from None


@router.get("/bots", response_model=list[BotSummary])
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


@router.get("/bots/{bot_id}", response_model=BotDetail)
def get_bot_endpoint(bot_id: str, lang: str = "en") -> BotDetail:
    bot = get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return _detail(bot, lang)


@router.post("/chat/identify", response_model=IdentifyResponse)
def identify(body: IdentifyRequest) -> IdentifyResponse:
    """Open the web chat as a phone number, the way WhatsApp opens as one.

    This is the whole of task 33: the visitor types the number their customer
    uses on WhatsApp and lands in that customer's record -- same key, same
    Redis, same conversation -- rather than in an anonymous session that knows
    nobody.

    Nothing is written here. Typing a number to look it up must not be the thing
    that creates a customer; only saying something is.
    """
    if not phone.is_bsuid(body.phone) and not phone.looks_like_a_phone(body.phone):
        # `identity` alone would take "call me at 7" and file someone under "7".
        # A number short enough to be a house number is a typo, not a customer.
        raise HTTPException(status_code=400, detail="Not a usable phone number")
    key = identity(body.phone)

    profile = user_store.get(key)
    if profile is None or profile.bot_id is None:
        return IdentifyResponse(key=key)

    bot = get_bot(profile.bot_id)
    if not bot:
        # A demo retired since they last wrote in. Same as WhatsApp: back to the
        # menu, rather than resuming a conversation nothing can answer.
        _start_over(profile)
        return IdentifyResponse(key=key)

    return IdentifyResponse(
        key=key,
        bot=_detail(bot, body.lang),
        history=[ChatTurn(role=m.role, content=m.content) for m in profile.history],
    )


@router.post("/chat/{key}/select", response_model=SelectBotResponse)
def select_bot(key: str, body: SelectBotRequest) -> SelectBotResponse:
    bot = get_bot(body.bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    profile = user_store.get_or_create(_identity_or_400(key))
    # Picking a demo starts that demo's conversation, exactly as choosing one off
    # the WhatsApp list does. The customer stays on file; only the talk is new.
    profile.bot_id = bot.id
    profile.history.clear()
    user_store.save(profile)

    disclaimer = _localize(bot.disclaimer, body.lang)
    suffix = GREETING_SUFFIX.get(body.lang, GREETING_SUFFIX["en"])
    greeting = f"{disclaimer}\n\n{suffix}"
    quick_questions = [_localize(q, body.lang) for q in bot.quick_questions]
    return SelectBotResponse(greeting=greeting, quick_questions=quick_questions)


@router.post("/chat/{key}/message", response_model=SendMessageResponse)
def send_message(key: str, body: SendMessageRequest) -> SendMessageResponse:
    profile = user_store.get_or_create(_identity_or_400(key))
    if not profile.bot_id:
        raise HTTPException(status_code=409, detail="No bot selected yet")

    bot = get_bot(profile.bot_id)
    if not bot:
        raise HTTPException(status_code=409, detail="This demo no longer exists")

    profile.add_message("user", body.message)
    # The customer record goes to the model, which is what makes this the same
    # path as WhatsApp rather than a parallel one: the real phone number is in
    # the system prompt, so the retail bot looks the caller up in the CRM
    # instead of asking whoever is sitting at the laptop who they are.
    reply = llm.get_reply(bot, profile, profile.history)
    profile.add_message("assistant", reply)
    # Saved after the turn is complete, so the conversation is on file for the
    # phone to pick up next -- the same trade in the other direction.
    user_store.save(profile)

    return SendMessageResponse(reply=reply)


@router.post("/chat/{key}/reset", response_model=ResetResponse)
def reset_session(key: str) -> ResetResponse:
    """Back to the demo menu, without forgetting who this is -- WhatsApp "menu"."""
    profile = user_store.get(_identity_or_400(key))
    if profile is not None:
        _start_over(profile)
    return ResetResponse(status="ok")


def _start_over(profile: UserProfile) -> None:
    profile.bot_id = None
    profile.history.clear()
    user_store.save(profile)
