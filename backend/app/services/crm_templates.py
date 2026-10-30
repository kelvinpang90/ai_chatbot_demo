"""The templates the CRM may send once a visitor's 24-hour window has closed.

Phase three of "demo number, many agents" (tasks/todo.md batch 11). The
contract is `docs/chatbot-phase3.md` section 5.3 in acuven_crm_demo: we hold the
whitelist (`CRM_TEMPLATES`, checked in `config.py`) because we hold Meta's
credentials, so the CRM can only send what is on it -- never a template name of
its own choosing.

Nothing here talks to Meta or Redis: finding a template, checking the values an
agent typed, and filling them in. `crm_send.send_template` does the sending.
"""
from __future__ import annotations

import re

from app.config import TEMPLATE_SLOT, CrmTemplate, settings

# What Meta refuses in a body parameter, as the contract lists it (section 5.3,
# rule 6; "not checked against Meta's current terms" there too). Anything that
# slips past is a 4xx from Meta, which the send reports as `rejected`.
_LINE_BREAK_OR_TAB = re.compile(r"[\n\r\t]")
_FOUR_SPACES = re.compile(r" {4,}")


class TemplateRefused(ValueError):
    """The request names a template or values the whitelist does not allow.

    The message says which rule, never the value: a parameter is usually the
    visitor's name.
    """


def listing() -> list[dict]:
    """The whitelist, as `POST /internal/crm/templates` returns it."""
    return [template.model_dump() for template in settings.crm_templates]


def find(name: str, language: str) -> CrmTemplate:
    """The whitelisted template by name and language, exactly as listed."""
    for template in settings.crm_templates:
        if template.name == name and template.language == language:
            return template
    raise TemplateRefused(f"{name}/{language} is not on the CRM template whitelist")


def checked_params(template: CrmTemplate, params: list[str]) -> list[str]:
    """The values to send, trimmed; raises `TemplateRefused` if any is not sendable.

    Trimmed once here and used for both the message and the rendered body, so
    what the visitor reads and what goes into the history are the same string.
    """
    if len(params) != len(template.params):
        raise TemplateRefused(
            f"{template.name}/{template.language} takes {len(template.params)} params, got {len(params)}"
        )
    values = []
    for position, (value, slot) in enumerate(zip(params, template.params), start=1):
        value = value.strip()
        if not 1 <= len(value) <= slot.max_len:
            raise TemplateRefused(f"param {position} must be 1-{slot.max_len} characters once trimmed")
        if _LINE_BREAK_OR_TAB.search(value):
            raise TemplateRefused(f"param {position} must not contain a line break or a tab")
        if _FOUR_SPACES.search(value):
            raise TemplateRefused(f"param {position} must not contain four or more spaces in a row")
        values.append(value)
    return values


def render(template: CrmTemplate, values: list[str]) -> str:
    """The body as the visitor will read it.

    One pass over the approved wording, so a value that itself reads `{{2}}`
    stays as typed instead of being filled in again.
    """
    return TEMPLATE_SLOT.sub(lambda slot: values[int(slot.group(1)) - 1], template.body)
