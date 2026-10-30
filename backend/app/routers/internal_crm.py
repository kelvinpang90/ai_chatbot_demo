"""The CRM's way in: its agents' replies, sent to WhatsApp through this service.

Phase two of "demo number, many agents" (tasks/todo.md batch 09). The contract
is `docs/chatbot-replies.md` sections 4 and 5 in acuven_crm_demo: the CRM signs
each request the way we sign our events to it (`services/crm_events.py`), with a
key of its own.

Only reachable inside the shared Docker networks -- neither nginx in front of
this service forwards `/internal/` -- but the signature is the gate, not the
network. This file is the gate (task 41.1); what a request that is through
does is `services/crm_send.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError, field_validator, model_validator

from app.config import settings
from app.services import crm_send, crm_templates, phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/crm")

# How far the CRM's timestamp may be from our clock, either way, in seconds.
SIGNATURE_WINDOW_SECONDS = 300

# Meta's cap on a text message, which is the contract's cap on the text.
MAX_TEXT_CHARS = 4096

# What the CRM sends after normalising a number: digits only, no `+`. ASCII
# digits on purpose -- `\d` would let Arabic-Indic digits through.
_PHONE = re.compile(r"[0-9]{8,15}")
_TIMESTAMP = re.compile(r"[0-9]{1,12}")


def _now() -> float:
    return time.time()


class Visitor(BaseModel):
    # Required: the CRM only replies to visitors it has a number for (D10).
    phone: str
    # Only for finding the visitor's record; the message goes to `phone`.
    bsuid: str | None = None

    @field_validator("phone")
    @classmethod
    def _normalised_number(cls, value: str | None) -> str | None:
        # None only reaches here on a hand-back, where the number is optional.
        if value is not None and not _PHONE.fullmatch(value):
            raise ValueError("phone must be 8-15 digits, as the CRM normalises it")
        return value

    @field_validator("bsuid")
    @classmethod
    def _a_bsuid_or_nothing(cls, value: str | None) -> str | None:
        if value is not None and not phone.is_bsuid(value):
            raise ValueError("bsuid is not one")
        return value.strip() if value is not None else None


class Agent(BaseModel):
    id: str
    name: str

    @field_validator("id", "name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SendRequest(BaseModel):
    """`POST /internal/crm/send`. Unknown keys are ignored.

    Strict on purpose: everything here comes from the CRM's own code, so a
    value out of shape is a bug over there, and a 422 shows it on the first
    request instead of on a customer's phone.
    """

    # The CRM's message id, and the idempotency key. Parsed, so the key is the
    # same however the CRM happens to case it.
    request_id: uuid.UUID
    visitor: Visitor
    text: str
    agent: Agent

    @field_validator("text")
    @classmethod
    def _sendable(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_TEXT_CHARS:
            raise ValueError(f"text must be 1-{MAX_TEXT_CHARS} characters once trimmed")
        return value


class TemplateChoice(BaseModel):
    """Which whitelisted template, and the values for its `{{n}}` slots in order.

    Only the shape here; whether the whitelist allows it is the route's check,
    after parsing, against `CRM_TEMPLATES` as it is at that moment.
    """

    name: str
    language: str
    params: list[str]

    @field_validator("name", "language")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SendTemplateRequest(BaseModel):
    """`POST /internal/crm/send-template` (phase-three contract, section 7).
    Same visitor, agent and key as `SendRequest`; a template in place of text."""

    request_id: uuid.UUID
    visitor: Visitor
    template: TemplateChoice
    agent: Agent


class HandbackVisitor(Visitor):
    """A hand-back may name a visitor the CRM has no usable number for -- one
    known only by BSUID can be handed back but not replied to (D10). One of the
    two is still required: with neither there is nobody to look up."""

    phone: str | None = None

    @model_validator(mode="after")
    def _someone(self) -> "HandbackVisitor":
        if not (self.phone or self.bsuid):
            raise ValueError("phone or bsuid is required")
        return self


class HandbackRequest(BaseModel):
    """`POST /internal/crm/handback`. Unknown keys are ignored."""

    # Only for the log: a hand-back is idempotent without a key.
    request_id: uuid.UUID
    visitor: HandbackVisitor
    agent: Agent


def _secrets() -> list[str]:
    return [secret for secret in (settings.crm_send_secret, settings.crm_send_secret_previous) if secret]


def _refuse(reason: str) -> HTTPException:
    # Says why, for whoever reads the log; never the key or the signature.
    logger.warning("internal crm: refused a request: %s", reason)
    return HTTPException(status_code=401, detail="Bad signature")


async def _verified_body(request: Request) -> bytes:
    """The raw body, once it is proven to be from the CRM. Raises otherwise.

    Shared by every route here (C4's hand-back is the next one). In the order
    the contract's status codes imply: no key configured is 503 before anything
    is read; a signature that does not check out is 401 before the body is
    parsed, so nobody unsigned learns from a 422 what a valid body looks like.

    Checked over the raw bytes, because those are what the CRM signed -- which
    is why the routes read the body themselves rather than declaring a model
    FastAPI would parse first.
    """
    if not settings.crm_send_secret:
        raise HTTPException(status_code=503, detail="CRM_SEND_SECRET is not configured")

    timestamp = request.headers.get("X-Acuven-Timestamp", "")
    signature = request.headers.get("X-Acuven-Signature", "")
    if not _TIMESTAMP.fullmatch(timestamp):
        raise _refuse("no usable X-Acuven-Timestamp")
    if abs(_now() - int(timestamp)) > SIGNATURE_WINDOW_SECONDS:
        raise _refuse("timestamp more than 300 seconds off -- check both clocks")
    if not signature.startswith("sha256="):
        raise _refuse("no sha256= X-Acuven-Signature")

    body = await request.body()
    signed = f"{timestamp}.".encode("utf-8") + body
    # Bytes on both sides: `compare_digest` raises on a non-ASCII str, and a
    # header is whatever the caller put in it. Starlette decodes headers as
    # latin-1, so this always round-trips.
    received = signature.removeprefix("sha256=").encode("latin-1")
    for secret in _secrets():
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected.encode("ascii"), received):
            return body
    raise _refuse("signature does not match -- check CRM_SEND_SECRET against the CRM's CHATBOT_SEND_SECRET")


def _parsed(model: type[BaseModel], body: bytes) -> BaseModel:
    try:
        return model.model_validate_json(body)
    except ValidationError as invalid:
        # Where and why, without echoing the input back: it is a customer's
        # number and an agent's message.
        problems = [{"loc": list(error["loc"]), "msg": error["msg"]} for error in invalid.errors()]
        logger.error("internal crm: the CRM sent a malformed %s: %s", model.__name__, problems)
        raise HTTPException(status_code=422, detail=problems) from None


@router.post("/send")
async def send(request: Request) -> JSONResponse:
    """Send one CRM agent's reply to a visitor. Contract section 5.

    Async only to read the raw body; the send itself -- Redis, then Meta, both
    blocking -- runs on the threadpool so it cannot stall the event loop that
    every other request is waiting on.
    """
    parsed = _parsed(SendRequest, await _verified_body(request))
    status, body = await run_in_threadpool(
        crm_send.send,
        request_id=str(parsed.request_id),
        phone=parsed.visitor.phone,
        bsuid=parsed.visitor.bsuid,
        text=parsed.text,
        agent_id=parsed.agent.id,
        agent_name=parsed.agent.name,
    )
    return JSONResponse(status_code=status, content=body)


@router.post("/send-template")
async def send_template(request: Request) -> JSONResponse:
    """Send one whitelisted template for a CRM agent. Contract section 7.

    Past the door, the whitelist: a name, language or value it does not allow
    is a 422 before the key is touched or Meta is called. The rest is `send`'s.
    """
    parsed = _parsed(SendTemplateRequest, await _verified_body(request))
    try:
        template = crm_templates.find(parsed.template.name, parsed.template.language)
        values = crm_templates.checked_params(template, parsed.template.params)
    except crm_templates.TemplateRefused as refused:
        # The rule, never the value: a parameter is usually the visitor's name.
        logger.error("internal crm: the CRM asked for a template the whitelist refuses: %s", refused)
        raise HTTPException(status_code=422, detail=[{"loc": ["body", "template"], "msg": str(refused)}]) from None
    status, body = await run_in_threadpool(
        crm_send.send_template,
        request_id=str(parsed.request_id),
        phone=parsed.visitor.phone,
        bsuid=parsed.visitor.bsuid,
        template=template,
        values=values,
        agent_id=parsed.agent.id,
        agent_name=parsed.agent.name,
    )
    return JSONResponse(status_code=status, content=body)


class TemplatesRequest(BaseModel):
    """`POST /internal/crm/templates`: an empty object. A POST only so that it
    is signed exactly like the others (phase-three contract, section 7)."""


@router.post("/templates")
async def templates(request: Request) -> JSONResponse:
    """The templates the CRM may send. Read fresh on every call; never cached."""
    _parsed(TemplatesRequest, await _verified_body(request))
    return JSONResponse(status_code=200, content={"templates": crm_templates.listing()})


@router.post("/handback")
async def handback(request: Request) -> JSONResponse:
    """Give a visitor's conversation back to the bot. Contract section 5.

    Same door as `send`; sends nothing to the visitor. On the threadpool for
    the same reason: the record is in Redis.
    """
    parsed = _parsed(HandbackRequest, await _verified_body(request))
    status, body = await run_in_threadpool(
        crm_send.hand_back,
        request_id=str(parsed.request_id),
        phone=parsed.visitor.phone,
        bsuid=parsed.visitor.bsuid,
        agent_id=parsed.agent.id,
        agent_name=parsed.agent.name,
    )
    return JSONResponse(status_code=status, content=body)
