from __future__ import annotations

from anthropic.lib.tools import BetaFunctionTool

from app.bots.registry import list_bots
from app.tools import crm, erp

# Every tool that exists, keyed by the name the model calls it by. That same name
# is what a bot's JSON lists, so one tool has one identity across the catalogue,
# the bot config and the console screen.
CATALOGUE: dict[str, BetaFunctionTool] = {tool.name: tool for tool in (*erp.TOOLS, *crm.TOOLS)}


def _resolve(bot_id: str, names: list[str]) -> list[BetaFunctionTool]:
    """The tools a bot declared, or a loud failure at startup.

    A typo in a bot's `tools` list is not a small mistake: it yields a bot that
    starts, answers, and quietly makes things up because the tool it needed was
    never attached. That is the exact failure this batch exists to remove, so it
    stops the process rather than the demo.
    """
    unknown = [name for name in names if name not in CATALOGUE]
    if unknown:
        raise ValueError(
            f"bot {bot_id!r} declares tools that do not exist: {', '.join(unknown)}. "
            f"Known tools: {', '.join(sorted(CATALOGUE))}."
        )
    return [CATALOGUE[name] for name in names]


# Which tools each bot may call, read from the bots' own JSON.
#
# A bot that lists none is not waiting for something: it takes the plain
# single-turn path in app.services.llm and behaves exactly as it did before the
# tool runner existed.
_TOOLS_BY_BOT: dict[str, list[BetaFunctionTool]] = {
    bot.id: _resolve(bot.id, bot.tools) for bot in list_bots()
}


def get_tools(bot_id: str) -> list[BetaFunctionTool]:
    return list(_TOOLS_BY_BOT.get(bot_id, []))
