from __future__ import annotations

from anthropic.lib.tools import BetaFunctionTool

# Which tools each bot is allowed to call, keyed by bot id.
#
# Every bot is empty today: batch 01 fills in the ERP and CRM tools, and task 11
# moves the declaration into each bot's own JSON. Until then an empty list is not
# a placeholder but a contract -- a bot with no tools takes the plain single-turn
# path in app.services.llm and behaves exactly as it did before the tool runner.
_TOOLS_BY_BOT: dict[str, list[BetaFunctionTool]] = {}


def get_tools(bot_id: str) -> list[BetaFunctionTool]:
    return list(_TOOLS_BY_BOT.get(bot_id, []))
