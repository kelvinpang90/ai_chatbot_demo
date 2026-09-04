import json
from pathlib import Path

from pydantic import BaseModel

DATA_DIR = Path(__file__).parent / "data"


class LocalizedText(BaseModel):
    zh: str
    en: str
    ms: str


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
    # The tools this bot may call, by name, resolved in app.tools.registry. Empty
    # means it answers from its context data alone, as every bot did before.
    tools: list[str] = []
    quick_questions: list[LocalizedText] = []


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
