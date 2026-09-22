"""The fifteen conversations worth opening, written rather than assembled (task 39.5).

`seed_lines.py` gives the console its weight: ninety customers, a question each,
enough of them that the list reads as a shop that has been busy for a month. This
gives it something to click on. One conversation for each industry in each
language, four or five turns long, with the things a template cannot do -- a
customer who changes their mind, one who asks for something the business does not
sell, one who wants an order that is not under their number -- and the answers a
person would want to have seen before buying this.

What is written here and what is not:

  * The customer's line and the bot's reply are written. Every figure in a reply
    has to be one the bot could have said: from its own `app/bots/data/*.json`,
    from what a tool returned, or from what the customer themselves just said.
    The handful the bot legitimately works out -- a ten percent deposit, a
    monthly repayment, breakfast for four -- are listed turn by turn in
    `derived`, so the list of numbers nobody checked is a list you can read.
  * The tool's output is not written. The seed calls the real tool and files what
    it answers today, the way every other seeded card is built (task 39.1). What
    the written reply leans on goes in `expects`, and the seed refuses the whole
    batch if the tool stops returning it -- a reply quoting a room at a rate the
    resort no longer has is the one thing on this screen a customer could catch.

Which tools a showcase may name is a short list on purpose. A conversation here
runs every night, so a tool that writes would file a booking every night for a
conversation that is only meant to be read; documents are task 39.2's to file and
enquiries task 39.4's. That leaves the tools that answer out of the bot's own
context data -- which are also the only ones whose answer a written reply can be
checked against, because that data is in this repository rather than in the ERP.

`request_human_help` is the exception, and it is not called. Its output is the
constant the live tool returns, because calling it would set the takeover flag
and put a span on the live feed -- both of which batch 07 says a seed must never
touch. The card is the one the tool draws; the flag it would have set is not set.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.bots.registry import get_bot
from app.tasks.seed_lines import LANGUAGES

SHOWCASE_FILE = Path(__file__).parent / "data" / "showcase.json"

# Tools a showcase turn may call for real: read-only, and answered out of the
# bot's own context data, so a written reply is checkable against this repo.
READ_ONLY_TOOLS = frozenset({"food_update_cart", "hotel_search_rooms", "saas_search_known_issues"})

# Named like a tool, answered from a constant. See the module docstring.
HANDOVER = "request_human_help"

_TURN_KEYS = {"ask", "reply", "tool", "tool_input", "expects", "derived"}
_SHOWCASE_KEYS = {"bot", "language", "note", "turns"}


class ShowcaseError(ValueError):
    """The file is wrong in a way that would show a customer something untrue."""


@dataclass(frozen=True)
class Turn:
    ask: str
    reply: str
    tool: str = ""
    tool_input: dict = field(default_factory=dict)
    # Substrings the reply leans on, which the live tool's output must contain.
    expects: tuple[str, ...] = ()
    # RM figures in the reply the bot worked out rather than read off a tool.
    derived: tuple[str, ...] = ()


@dataclass(frozen=True)
class Showcase:
    bot_id: str
    language: str
    # One line for whoever reads this file, and nowhere near the console.
    note: str
    turns: tuple[Turn, ...]


def load(path: Path = SHOWCASE_FILE) -> dict[tuple[str, str], Showcase]:
    """Every showcase, keyed by (bot, language). Raises rather than skip a bad one.

    Loud for the same reason the rest of the seed is: a showcase quietly dropped
    is a customer on the console whose conversation is a template after all, and
    nobody would notice until they clicked it in front of somebody.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    records = document.get("conversations")
    if not isinstance(records, list) or not records:
        raise ShowcaseError(f"{path} has no conversations")
    showcases: dict[tuple[str, str], Showcase] = {}
    for index, record in enumerate(records):
        showcase = _showcase(record, index)
        key = (showcase.bot_id, showcase.language)
        if key in showcases:
            raise ShowcaseError(f"two showcases for {key}; one conversation per industry per language")
        showcases[key] = showcase
    return showcases


def _showcase(record: dict, index: int) -> Showcase:
    where = f"conversation {index}"
    _only(record, _SHOWCASE_KEYS, where)
    bot_id = str(record.get("bot", ""))
    bot = get_bot(bot_id)
    if bot is None:
        raise ShowcaseError(f"{where}: no bot called {bot_id!r}")
    language = str(record.get("language", ""))
    if language not in LANGUAGES:
        raise ShowcaseError(f"{where}: {language!r} is not one of {LANGUAGES}")
    if not str(record.get("note", "")).strip():
        raise ShowcaseError(f"{where}: no note saying what this one is for")
    raw = record.get("turns")
    if not isinstance(raw, list) or len(raw) < 3:
        raise ShowcaseError(f"{where}: a showcase is at least three turns, or it is a template")
    turns = tuple(_turn(row, bot, f"{bot_id}/{language} turn {n}") for n, row in enumerate(raw))
    handovers = [n for n, turn in enumerate(turns) if turn.tool == HANDOVER]
    if handovers and handovers != [len(turns) - 1]:
        # `request_human_help` tells the bot to stop and say nothing further, so
        # a turn after it is a bot talking over the colleague who just took over.
        raise ShowcaseError(f"{bot_id}/{language}: {HANDOVER} has to be the last turn, it is the one that stops the bot")
    return Showcase(bot_id=bot_id, language=language, note=record["note"], turns=turns)


def _turn(row: dict, bot, where: str) -> Turn:
    if not isinstance(row, dict):
        raise ShowcaseError(f"{where}: not a turn")
    _only(row, _TURN_KEYS, where)
    ask, reply = str(row.get("ask", "")).strip(), str(row.get("reply", "")).strip()
    if not ask or not reply:
        raise ShowcaseError(f"{where}: a turn is something asked and something answered")
    tool = str(row.get("tool", ""))
    tool_input = row.get("tool_input") or {}
    expects = tuple(row.get("expects") or ())
    derived = tuple(row.get("derived") or ())
    if tool:
        if tool not in bot.tools:
            raise ShowcaseError(f"{where}: {bot.id} has no tool called {tool!r}, so it could never draw that card")
        if tool not in READ_ONLY_TOOLS and tool != HANDOVER:
            raise ShowcaseError(
                f"{where}: {tool!r} is not one a showcase may call. A seeded conversation runs every"
                f" night, so it may only call a tool that writes nothing: {', '.join(sorted(READ_ONLY_TOOLS))}."
            )
        if not isinstance(tool_input, dict):
            raise ShowcaseError(f"{where}: tool_input is what the model filled in, so it is an object")
        if tool == HANDOVER and expects:
            raise ShowcaseError(f"{where}: {HANDOVER} answers with a constant, so there is nothing to expect of it")
        if tool in READ_ONLY_TOOLS and not expects:
            raise ShowcaseError(
                f"{where}: say in `expects` what the reply took from {tool!r}, or nothing checks that it is still true"
            )
    elif tool_input or expects:
        raise ShowcaseError(f"{where}: tool_input and expects belong to a turn that calls a tool")
    for figure in derived:
        if figure not in reply:
            raise ShowcaseError(f"{where}: {figure!r} is listed as worked out but is not in the reply")
    return Turn(ask=ask, reply=reply, tool=tool, tool_input=tool_input, expects=expects, derived=derived)


def _only(record: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(record) - allowed)
    if unknown:
        raise ShowcaseError(f"{where}: {', '.join(unknown)} is not something this file understands")
