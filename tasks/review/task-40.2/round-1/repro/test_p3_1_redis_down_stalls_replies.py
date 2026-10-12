"""P3-1 (reviewer, task 40.2 round 1).

With the CRM queue switched on and Redis unreachable, every `crm_events.enqueue`
blocks the customer's thread for the full 1-second connect timeout -- and task
40.2 puts one between every pair of messages in a multi-message reply (the
`ai_reply` for message N is queued before message N+1 is sent). So a Redis
outage makes the bot's greeting arrive, then pause a second, then its buttons.
`user_store` -- the same Redis -- has a go-offline switch for exactly this and
costs nothing per message after the first failure; `crm_events` has none.

Real input: real redis-py client (the module's own `_default_client`) aimed at a
non-routable address, i.e. what a stopped/unreachable `infra_redis` looks like
from the container. Only Meta and the model are stubbed.
"""
import time
from unittest.mock import patch

import httpx

from app.config import settings
from app.routers.whatsapp_webhook import _handle_incoming_message
from app.services import crm_events, llm, whatsapp

PHONE = "60123457777"
UNREACHABLE = "redis://10.255.255.1:6379/16"


def test_an_unreachable_redis_does_not_pause_the_reply_between_messages():
    send_times = []

    def meta_accepts(payload):
        send_times.append(time.monotonic())
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out.{len(send_times)}"}]})

    crm_events.reset()
    try:
        with patch.object(settings, "crm_events_enabled", True), \
                patch.object(settings, "crm_events_secret", "s"), \
                patch.object(settings, "redis_url", UNREACHABLE), \
                patch.object(crm_events, "_client_factory", crm_events._default_client), \
                patch.object(whatsapp, "send_raw", side_effect=meta_accepts), \
                patch.object(llm, "get_reply", return_value="ok"):
            # Picking a demo off the menu: the greeting, then the quick-question buttons.
            started = time.monotonic()
            _handle_incoming_message(
                {"id": "wamid.in.pick", "from": PHONE, "timestamp": "1760000000", "type": "interactive",
                 "interactive": {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}}},
                {"wa_id": PHONE, "profile": {"name": "X"}},
            )
            total = time.monotonic() - started
    finally:
        crm_events.reset()

    assert len(send_times) >= 2, "expected greeting + buttons"
    gap = send_times[1] - send_times[0]
    first = send_times[0] - started
    print(f"first send after {first:.2f}s, gap between greeting and buttons {gap:.2f}s, turn {total:.2f}s")
    # The customer is waiting on this thread. The CRM is a side channel.
    assert gap < 0.5, f"Redis being down held the buttons back {gap:.2f}s after the greeting"
    assert total < 1.5, f"Redis being down added {total:.2f}s to one turn"
