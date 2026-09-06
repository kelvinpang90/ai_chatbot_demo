"""What a demo costs, in the currency the person watching thinks in.

Tokens are not a unit a shop owner has any feel for. Ringgit are. The whole
point of this module is the one line it feeds on the director's console -- "this
conversation cost RM 0.14" -- because "will this be expensive?" is usually the
real question behind the ones being asked out loud.
"""
from __future__ import annotations

# USD per million tokens, as published. Cache writes are 1.25x the input rate
# (the 5-minute TTL, which is what `cache_control: ephemeral` asks for) and cache
# reads 0.1x, so both are derived below rather than typed out and left to drift.
_USD_PER_MTOK = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# A model we have no rate for is priced as the most expensive one in use. Quoting
# too high loses an argument we would otherwise have won; quoting too low is a
# promise we cannot keep.
_FALLBACK = _USD_PER_MTOK["claude-opus-5"]

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1

# Hand-set, not a live quote -- a demo does not need a forex feed, and being a
# few percent off moves the last digit of a figure already under one ringgit.
# Change it when it has drifted far enough to matter.
USD_TO_MYR = 4.30


def _rates(model: str) -> tuple[float, float]:
    return _USD_PER_MTOK.get(model, _FALLBACK)


def usage_tokens(usage) -> dict[str, int]:
    """The four counts that get billed, flattened out of an SDK usage object.

    `input_tokens` is the uncached input only; the two cache counts are billed
    separately and at different rates, which is why all four travel together.
    """
    return {
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def cost_myr(model: str, tokens: dict[str, int]) -> float:
    """Ringgit for one API call. Four token counts, each at its own rate."""
    input_rate, output_rate = _rates(model)
    usd = (
        tokens["input"] * input_rate
        + tokens["output"] * output_rate
        + tokens["cache_write"] * input_rate * CACHE_WRITE_MULTIPLIER
        + tokens["cache_read"] * input_rate * CACHE_READ_MULTIPLIER
    ) / 1_000_000
    return usd * USD_TO_MYR
