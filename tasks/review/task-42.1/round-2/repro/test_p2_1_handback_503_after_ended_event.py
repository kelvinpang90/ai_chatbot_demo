"""P2-1 (round 2): when the record's save fails, the round-1 fix answers the CRM
503 "unavailable" (that is, not ended, retry). But the `handover_changed`
active=False event has already been queued by then.

`handover.end` saves the record and then, unconditionally, calls `_tell_crm`,
which pushes `handover_changed {active: false}` onto the CRM queue. That queue
has its own Redis client and its own breaker (`crm_events._offline_until`), so a
SET on the visitor store that times out does not stop an RPUSH a millisecond
later on the other connection. `hand_back` only checks `user_store.offline()`
*after* `handover.end` has returned, so by then the event is already queued.

The CRM's consumer (acuven_crm_demo `chatbot_event_service.update_handover`)
stores `wa_handover_active = False` from that event whatever the synchronous
answer was. So the CRM shows the visitor as back with the bot. The copy in Redis
is still held, and once the store comes back online it is read again, so the bot
stays silent on the visitor (up to HANDOVER_IDLE_SECONDS). That is the harm P2-1
in round 1 was about, now reached by the fix's second branch. The 503 tells the
agent to retry, while the screen, fed by the event, tells them there is nothing
left to hand back.

The input is real: redis' own TimeoutError on the SET, which is what a stalled
Redis gives a client with `socket_timeout=1.0`. The event queue is the repo's
real `crm_events.enqueue`, with only its Redis client stood in.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.services import crm_events, handover, whatsapp
from app.services.user_store import user_store

SECRET = "repro-send-secret"
NOW = int(time.time())
PHONE = "60123456789"


class StallingRedis:
    """A dict-backed Redis for the visitor store whose writes can time out."""

    def __init__(self):
        self.data = {}
        self.stall_writes = False

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if self.stall_writes:
            raise redis.exceptions.TimeoutError("Timeout reading from socket")
        self.data[key] = value
        return True

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def world(monkeypatch):
    store_redis = StallingRedis()
    pushed = []
    queue_redis = MagicMock()
    queue_redis.rpush.side_effect = lambda key, value: pushed.append(json.loads(value))

    user_store.reset()
    crm_events.reset()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: queue_redis)
    with patch.object(user_store, "_url", "redis://infra_redis:6379/3"), \
            patch.object(user_store, "_client_factory", lambda url: store_redis), \
            patch.object(settings, "redis_url", "redis://infra_redis:6379/3"), \
            patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "crm_events_secret", "repro-events-secret"), \
            patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(internal_crm, "_now", lambda: NOW), \
            patch.object(whatsapp, "send_raw", side_effect=AssertionError("a hand-back sends nothing")):
        yield store_redis, pushed
    user_store.reset()
    crm_events.reset()


def _post():
    body = json.dumps({
        "request_id": "11111111-2222-4333-8444-555555555555",
        "visitor": {"phone": PHONE, "bsuid": None},
        "agent": {"id": "user-9", "name": "Manager Lim"},
    }).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return TestClient(app).post("/internal/crm/handback", content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def test_a_503_hand_back_does_not_tell_the_crm_the_takeover_ended(world):
    store_redis, pushed = world
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(PHONE))
    assert handover.active(user_store.get(PHONE))
    pushed.clear()

    store_redis.stall_writes = True  # the SET of the ended record times out
    response = _post()

    ended_events = [
        e for e in pushed
        if e["type"] == "handover_changed" and e["handover"]["active"] is False
    ]
    # The chatbot's own view of the outcome once the store is back: Redis still held.
    store_redis.stall_writes = False
    user_store._offline_until = 0.0
    still_held = handover.active(user_store.get(PHONE))

    assert not (response.status_code != 200 and ended_events), (
        f"answered {response.status_code} {response.json()} (not ended, retry), "
        f"but queued {len(ended_events)} handover_changed active=False event(s) the CRM will store; "
        f"visitor still held in Redis: {still_held}"
    )
