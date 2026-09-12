from __future__ import annotations

from anthropic.lib.tools import BetaFunctionTool

from app.bots.registry import list_bots
from app.tools import crm, erp, human, local

# Every tool that exists, keyed by the name the model calls it by. That same name
# is what a bot's JSON lists, so one tool has one identity across the catalogue,
# the bot config and the console screen.
CATALOGUE: dict[str, BetaFunctionTool] = {
    tool.name: tool for tool in (*erp.TOOLS, *crm.TOOLS, *local.TOOLS, *human.TOOLS)
}


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


# The control arm (task 12.2). Thrown from the director's console, it detaches
# every tool from every bot at once, so the same bot answering the same question
# has nothing but the JSON in its prompt to answer from -- which is the whole
# claim of this demo, made checkable in front of the customer instead of
# explained to them. Emptying the list here rather than anywhere further in is
# deliberate: a bot with no tools already has a code path of its own, tested
# since task 2, and this switch simply walks every bot down it.
#
# Process-global, and deliberately not persisted: it is the same screen, the same
# minute, the same operator. A restart mid-demo comes back with the tools on,
# which is the safe way round -- the failure it rules out is a demo that quietly
# stays crippled after a redeploy nobody noticed.
_tools_enabled = True


def tools_enabled() -> bool:
    return _tools_enabled


def set_tools_enabled(enabled: bool) -> bool:
    global _tools_enabled
    _tools_enabled = enabled
    return _tools_enabled


def get_tools(bot_id: str) -> list[BetaFunctionTool]:
    if not _tools_enabled:
        return []
    return list(_TOOLS_BY_BOT.get(bot_id, []))
