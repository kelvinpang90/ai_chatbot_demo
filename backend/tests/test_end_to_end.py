"""One conversation, end to end: Meta's webhook in, a row in the CRM out.

Everything between is the real thing -- the signature check, the session store,
the bot and identity registries, the SDK's tool runner, the shipped
`crm_create_lead`, and the client that talks to crm_os. Only the three parties
outside this process stand in for themselves, each at its own HTTP boundary:
Meta calling us, Anthropic's Messages API, and crm_os.

The per-layer tests each prove one seam holds. These are the ones that fail when
every seam is fine and nothing is joined up -- a tool written correctly that the
model is never offered, a tool result that never gets back to the model, a reply
that never leaves the process.

Nothing in the chain is stubbed any more. Task 11 mounted the tools, so the
registry lookup that used to be handed `crm.TOOLS` now reads `retail`'s own JSON
like it does in production -- which is why this file no longer patches
`llm.get_tools`. If that declaration ever loses `crm_create_lead`, these tests go
red rather than passing on a tool list the shipped bot does not have.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
from unittest.mock import patch

import httpx
import pytest
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage
from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.console import events
from app.main import app
from app.services import llm, whatsapp
from app.tools import crm

APP_SECRET = "not-a-real-app-secret"

# The rojak opener from the flagship script, which is the point: one sentence
# mixing English, Malay grammar and a Malaysian payment habit.
ENQUIRY = "Boss this earbuds got stock ah? I want 2, can COD?"
LEAD_TITLE = "2 units Sony WF-C710N earbuds, COD"
LEAD_PHONE = "+60 12-333 4444"
LEAD_AMOUNT = 657.80

FINAL_REPLY = "Got it bos! I've passed your details to our sales team, they'll call you shortly."

CONTACT = {"id": "c-e2e", "name": "Ahmad Faizal", "phone": LEAD_PHONE}
DEAL = {"id": "d-e2e", "title": LEAD_TITLE, "amount": LEAD_AMOUNT, "status": "lead"}


def _response(status: int, payload: dict, url: str, method: str = "GET") -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request(method, url))


def _cloudflare(status: int, url: str) -> httpx.Response:
    """What Cloudflare returns for an origin it got no usable answer from."""
    return httpx.Response(
        status,
        content=b"<!DOCTYPE html><html><body>Error 520</body></html>",
        headers={"content-type": "text/html; charset=UTF-8", "server": "cloudflare"},
        request=httpx.Request("POST", url),
    )


class FakeCrmOs:
    """crm_os at its HTTP boundary: answers like the routes do, keeps the writes."""

    def __init__(self, *, write_status: int | None = None) -> None:
        self.write_status = write_status
        self.posted: list[tuple[str, dict]] = []

    def get(self, url, **_kwargs):
        if url.endswith("/api/contacts"):  # the phone lookup, nobody on file
            empty = {"data": [], "total": 0, "page": 1, "page_size": 100}
            return _response(200, {"success": True, "data": empty}, url)
        if url.endswith("/api/deals"):  # the card POST /api/contacts just made
            return _response(200, {"success": True, "data": [DEAL]}, url)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, **kwargs):
        if url.endswith("/api/auth/login"):
            tokens = {"access_token": "acc", "refresh_token": "ref"}
            return _response(200, {"success": True, "data": tokens}, url, "POST")

        self.posted.append((url, kwargs.get("json") or {}))
        if url.endswith("/api/contacts"):
            if self.write_status:
                return _cloudflare(self.write_status, url)
            return _response(201, {"success": True, "data": CONTACT}, url, "POST")
        if url.endswith("/activities"):
            return _response(201, {"success": True, "data": {"id": "act-e2e"}}, url, "POST")
        raise AssertionError(f"unexpected POST {url}")

    def paths(self) -> list[str]:
        return [url.split("kelvinpeng.com")[-1].split(".test")[-1] for url, _ in self.posted]

    def body_for(self, suffix: str) -> dict:
        (body,) = [sent for url, sent in self.posted if url.endswith(suffix)]
        return body


class Customer:
    """One person's WhatsApp thread.

    A fresh number and fresh message ids per test on purpose: the session store
    and the duplicate-message guard both live for the life of the process, so a
    second test reusing a number would start mid-conversation and a reused
    message id would be dropped as already seen -- silently, which is the worst
    way for a test to be wrong.
    """

    _numbers = itertools.count(1)

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.phone = f"60123{next(Customer._numbers):06d}"
        self._ids = itertools.count(1)

    def says(self, text: str) -> None:
        self._deliver({"type": "text", "text": {"body": text}})

    def chooses(self, option_id: str) -> None:
        self._deliver(
            {
                "type": "interactive",
                "interactive": {"type": "list_reply", "list_reply": {"id": option_id}},
            }
        )

    def _deliver(self, message: dict) -> None:
        """Hand Meta's webhook one message, signed the way Meta signs it."""
        message = {"id": f"wamid.{self.phone}.{next(self._ids)}", "from": self.phone, **message}
        body = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
        digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/webhook/whatsapp",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={digest}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200


def _assistant(content: list, stop_reason: str) -> BetaMessage:
    return BetaMessage(
        id="msg_e2e",
        model="claude-opus-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        content=content,
        usage=BetaUsage(input_tokens=1, output_tokens=1),
    )


def _wants_the_lead_written() -> BetaMessage:
    return _assistant(
        [
            BetaToolUseBlock(
                type="tool_use",
                id="tu_lead",
                name="crm_create_lead",
                input={
                    "name": "Ahmad Faizal",
                    "phone": LEAD_PHONE,
                    "requirement": LEAD_TITLE,
                    "amount": LEAD_AMOUNT,
                },
            )
        ],
        "tool_use",
    )


@pytest.fixture
def customer(crm_credentials):
    """A signed webhook, a customer nobody has met, and an empty console."""
    events.clear()
    with patch.object(settings, "whatsapp_app_secret", APP_SECRET):
        with TestClient(app) as client:
            yield Customer(client)
    events.clear()


def _walk_up_to_the_question(customer: Customer, sent: list) -> None:
    """Say hello, pick the retail demo, pick an identity. All real router code."""
    customer.says("hi")
    customer.chooses("retail")
    customer.chooses(get_bot("retail").identities[0].id)

    # The menu, the identity list, then the greeting and its quick-reply buttons.
    assert len(sent) == 4


def _tool_results_fed_back(parse_mock) -> list[str]:
    """What the model was actually shown after the tools ran."""
    second_turn = parse_mock.call_args_list[1].kwargs["messages"]
    return [
        str(block.get("content"))
        for message in second_turn
        for block in (message["content"] if isinstance(message["content"], list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def test_a_customer_message_becomes_a_card_in_the_crm_and_a_reply_on_whatsapp(customer):
    crm_os = FakeCrmOs()
    turns = [_wants_the_lead_written(), _assistant([BetaTextBlock(type="text", text=FINAL_REPLY)], "end_turn")]

    with patch.object(whatsapp, "send_raw") as send:
        with patch.object(llm._client.beta.messages, "parse", side_effect=turns) as parse:
            with patch.object(llm.settings, "anthropic_api_key", "sk-not-real"):
                with patch("app.services.api_client.httpx.get", side_effect=crm_os.get):
                    with patch("app.services.api_client.httpx.post", side_effect=crm_os.post):
                        _walk_up_to_the_question(customer, send.call_args_list)
                        customer.says(ENQUIRY)

    # 1. The CRM got the lead, as one card rather than two.
    assert crm_os.paths() == ["/api/contacts", "/api/deals/d-e2e/activities"]
    assert crm_os.body_for("/api/contacts")["initial_title"] == LEAD_TITLE
    assert crm_os.body_for("/api/contacts")["initial_amount"] == LEAD_AMOUNT

    # 2. The note the salesperson reads is on the card, marked WhatsApp.
    note = crm_os.body_for("/activities")
    assert note["type"] == "WhatsApp"
    assert LEAD_TITLE in note["content"]

    # 3. The model was shown what the tool returned, not left to guess.
    (result,) = _tool_results_fed_back(parse)
    assert '"deal_id": "d-e2e"' in result
    assert '"activity_logged": true' in result

    # 4. The customer got the answer, on the number they wrote from.
    last = send.call_args_list[-1].args[0]
    assert last["to"] == customer.phone
    assert last["text"]["body"] == FINAL_REPLY

    # 5. The console the demo runs on saw the call happen.
    kinds = [(e.type, e.tool) for e in events.since(0)]
    assert (events.TOOL_START, "crm_create_lead") in kinds
    assert (events.TOOL_END, "crm_create_lead") in kinds


def test_a_cloudflare_error_reaches_the_model_as_not_known_rather_than_not_saved(customer):
    """The round 3 P1, from the customer's message to what the model is told.

    A 520 means the write reached crm_os and no usable answer came back, so the
    row may be there. If that arrives as "nothing was recorded, try once more",
    the model tries again and the board grows a second card for one customer.
    """
    crm_os = FakeCrmOs(write_status=520)
    turns = [_wants_the_lead_written(), _assistant([BetaTextBlock(type="text", text=FINAL_REPLY)], "end_turn")]

    with patch.object(whatsapp, "send_raw") as send:
        with patch.object(llm._client.beta.messages, "parse", side_effect=turns) as parse:
            with patch.object(llm.settings, "anthropic_api_key", "sk-not-real"):
                with patch("app.services.api_client.httpx.get", side_effect=crm_os.get):
                    with patch("app.services.api_client.httpx.post", side_effect=crm_os.post):
                        _walk_up_to_the_question(customer, send.call_args_list)
                        customer.says(ENQUIRY)

    (result,) = _tool_results_fed_back(parse)
    assert result.strip("[]'\" ") == crm.LEAD_UNKNOWN or crm.LEAD_UNKNOWN in result
    assert crm.LEAD_FAILED not in result

    # The customer is still answered -- a back office that fell over is not the
    # customer's problem, and a silent bot is the one failure they always notice.
    assert send.call_args_list[-1].args[0]["text"]["body"] == FINAL_REPLY

    # And the console shows the call that went wrong, rather than nothing at all.
    ends = [e for e in events.since(0) if e.type == events.TOOL_END]
    assert [e.tool for e in ends] == ["crm_create_lead"]
