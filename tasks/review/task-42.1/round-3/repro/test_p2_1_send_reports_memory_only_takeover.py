"""P2-1 (round 3): the round-2 fix stops the *event* from reporting a takeover that
only reached memory, but `crm_send.send` still reports the same memory-only
takeover in its synchronous answer, the one the CRM stores first.

`_take_over` calls `handover.begin`, whose `user_store.save` times out on the
visitor store. The save falls back to memory and starts the 30 s offline window,
so `_tell_crm` now (38556e7) logs "changed in memory only ... not telling the
CRM" and queues nothing. `_take_over` then returns
`{active: True, expires_at: now + HANDOVER_IDLE_SECONDS, occurred_at}` anyway, and `send` answers
200 with it. The idempotency key has its own Redis client with no breaker, so a
stalled SET on the store does not stop the send.

The CRM stores `wa_handover_active=True` from the response. The copy in Redis
was never written, so once the window ends the bot reads "not held" and
answers the visitor over the agent, while the CRM shows the agent holding the
conversation for 24 hours. The new `_tell_crm` docstring describes exactly
this harm, and the new test says "the same rule for every change". The rule is
applied to one of the two channels that tell the CRM. Contract R3 ("the CRM
gets one value from both") is also broken now: a response with a takeover and
no event for it.

The input is real: redis' own TimeoutError on the store's SET, which is what a
stalled Redis gives a client with socket_timeout=1.0. Meta is stubbed at
httpx.post, the way tests/test_crm_send.py does it.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
import redis
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.services import crm_events, crm_send, handover
from app.services.user_store import user_store
from app.session_store import session_store

SECRET = "repro-send-secret"
NOW = int(time.time())
PHONE = "60123456789"
REQUEST_ID = "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"


class StoreRedis:
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


class KeyRedis:
    """The idempotency key's Redis: healthy, separate client."""

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def delete(self, key):
        return 1 if self.values.pop(key, None) is not None else 0


@pytest.fixture
def world(monkeypatch):
    store_redis = StoreRedis()
    pushed = []
    queue_redis = MagicMock()
    queue_redis.rpush.side_effect = lambda key, value: pushed.append(json.loads(value))
    key_redis = KeyRedis()

    session_store.reset()
    user_store.reset()
    crm_events.reset()
    crm_send.reset()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: queue_redis)
    monkeypatch.setattr(crm_send, "_client_factory", lambda url: key_redis)
    accepted = lambda url, **kw: httpx.Response(
        200, json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.SENT1"}]},
        request=httpx.Request("POST", url),
    )
    with patch.object(user_store, "_url", "redis://infra_redis:6379/3"), \
            patch.object(user_store, "_client_factory", lambda url: store_redis), \
            patch.object(settings, "redis_url", "redis://infra_redis:6379/3"), \
            patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "crm_events_secret", "repro-events-secret"), \
            patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(internal_crm, "_now", lambda: NOW), \
            patch("app.services.whatsapp.httpx.post", side_effect=accepted):
        yield store_redis, pushed
    session_store.reset()
    user_store.reset()
    crm_events.reset()
    crm_send.reset()


def _post():
    body = json.dumps({
        "request_id": REQUEST_ID,
        "visitor": {"phone": PHONE, "bsuid": None},
        "text": "Hello from the CRM",
        "agent": {"id": "user-7", "name": "Mei"},
    }).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return TestClient(app).post("/internal/crm/send", content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def test_a_send_does_not_report_a_takeover_that_never_reached_redis(world):
    store_redis, pushed = world
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)
    assert not handover.active(user_store.get(PHONE))

    store_redis.stall_writes = True  # the store's SET of the taken-over record times out
    response = _post()

    # The bot's own view once the store is read again: what Redis holds.
    store_redis.stall_writes = False
    user_store._offline_until = 0.0
    held_in_redis = handover.active(user_store.get(PHONE))
    changes = [e for e in pushed if e["type"] == "handover_changed"]

    assert response.status_code == 200 and response.json()["result"] == "sent"
    reported = response.json()["handover"]
    assert not (reported and reported["active"] and not held_in_redis), (
        f"answered handover={reported} (CRM stores: agent holds the visitor), "
        f"but Redis holds the visitor: {held_in_redis}; handover_changed events queued: {len(changes)}"
    )
