import json
from pathlib import Path

from pydantic import BaseModel

DATA_DIR = Path(__file__).parent / "data"


class LocalizedText(BaseModel):
    zh: str
    en: str
    ms: str


class Identity(BaseModel):
    id: str
    label: LocalizedText
    profile: dict


class BotConfig(BaseModel):
    id: str
    name: LocalizedText
    description: LocalizedText
    icon: str
    disclaimer: LocalizedText
    persona_prompt: str
    # Which Claude model answers for this bot. Unset falls back to settings.anthropic_model.
    model: str | None = None
    context_data: dict = {}
    quick_questions: list[LocalizedText] = []
    identities: list[Identity]


def _load_bot(path: Path) -> BotConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    return BotConfig(**data)


def _load_all() -> dict[str, BotConfig]:
    return {bot.id: bot for bot in (_load_bot(p) for p in sorted(DATA_DIR.glob("*.json")))}


_BOTS = _load_all()


def list_bots() -> list[BotConfig]:
    return list(_BOTS.values())


def get_bot(bot_id: str) -> BotConfig | None:
    return _BOTS.get(bot_id)


def get_identity(bot_id: str, identity_id: str) -> Identity | None:
    bot = get_bot(bot_id)
    if not bot:
        return None
    return next((i for i in bot.identities if i.id == identity_id), None)
