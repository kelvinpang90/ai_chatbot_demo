"""The one tool that is about the conversation rather than about the business.

Every other tool answers a question or writes a record. This one stops the bot
talking: it is the answer to "and when it cannot cope?", which is the last thing
anybody asks before buying. Kept out of `local.py` because that module is the
light-tier bots' stand-in back offices, and this belongs to every bot that has
tools at all.
"""
from __future__ import annotations

import logging

from anthropic import beta_tool

from app.services import handover
from app.tools import local

logger = logging.getLogger(__name__)

# -- handing over to a person (task 20) ----------------------------------------

HANDED_OVER = (
    "A colleague has been brought in and will answer from here. Tell the customer "
    "plainly that you are passing them to a colleague who will take it from here, "
    "in one short sentence, and then stop -- do not attempt the request yourself, "
    "do not promise what the colleague will decide, and do not ask them anything "
    "else. Everything they say from now on goes to that person, not to you."
)
NO_ONE_TO_HAND_TO = (
    "There is nobody to hand this conversation to on this channel, so it stays "
    "with you. Do not tell the customer you are transferring them. Say what you "
    "can and cannot do, and offer to take their details so somebody can call back."
)


@beta_tool
def request_human_help(reason: str) -> str:
    """Hand this conversation to a human colleague and stop answering.

    Call this when the customer asks for a person, or when what they want is
    outside what your tools can do and guessing would be worse than waiting --
    a request to change something already dispatched, a complaint that needs a
    decision, a price only a manager can give.

    This is not a soft option and not an apology: once it is called, everything
    the customer writes goes to a person and you say nothing further until that
    person hands the conversation back. So do not call it to get out of a
    question you can answer, and do not call it twice.

    Args:
        reason: Why this needs a person, in one line, for the colleague who is
            about to pick it up cold. What the customer asked for and anything
            you have already established -- they can see the conversation, so
            do not repeat it, tell them what it adds up to.
    """
    customer = local.customer()
    if customer is None:
        # The web chat, and any other caller with no conversation a person could
        # be dropped into. Better to say so than to let the bot promise a
        # colleague who will never arrive.
        logger.info("request_human_help called with no customer to hand over")
        return NO_ONE_TO_HAND_TO
    # The record the router is holding for this turn, not a copy of it: the
    # router saves that object when the turn ends, and a flag set on anything
    # else is a flag that object is about to overwrite. See `handover.begin`.
    if not handover.begin(customer, reason=str(reason or "").strip()):
        return NO_ONE_TO_HAND_TO
    return HANDED_OVER


TOOLS = [request_human_help]
