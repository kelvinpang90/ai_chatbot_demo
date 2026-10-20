"""The CRM's way in: its agents' replies, sent to WhatsApp through this service.

Phase two of "demo number, many agents" (tasks/todo.md batch 09). The contract
is `docs/chatbot-replies.md` sections 4 and 5 in acuven_crm_demo: the CRM signs
each request the way we sign our events to it (`services/crm_events.py`), with a
key of its own.

Only reachable inside the shared Docker networks -- neither nginx in front of
this service forwards `/internal/` -- but the signature is the gate, not the
network. Task 41.1 is the gate alone; what happens once a request is through
arrives in 41.2.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError, field_validator

from app.config import settings
from app.services import phone

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
    def _normalised_number(cls, value: str) -> str:
        if not _PHONE.fullmatch(value):
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

    Task 41.1 stops at the door: what a request that gets through does --
    idempotency, the send, the takeover -- is 41.2 and 41.3. Undeployable as a
    half-built endpoint it is not: with CRM_SEND_SECRET unset, which it is on
    the VPS until both sides are done, nothing gets past the 503.
    """
    _parsed(SendRequest, await _verified_body(request))
    return JSONResponse(status_code=501, content={"result": "not_implemented"})
