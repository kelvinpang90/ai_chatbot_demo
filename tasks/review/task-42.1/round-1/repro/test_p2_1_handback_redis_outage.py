"""P2-1: a Redis blip makes `/internal/crm/handback` answer 200 `not_active`
for a visitor who is still held.

`user_store.get` never raises: on a Redis read failure it goes offline and
reads its in-process memory instead, which does not hold the record. `hand_back`
takes that None as "nobody holds this visitor" and tells the CRM so -- a
definite claim (contract section 5: "没有档案或本来就没接管") that is false. The
CRM keeps its state, the agent's hand-back never happened, and the bot stays
silent on the visitor (now up to HANDOVER_IDLE_SECONDS = 24 h, C4) with no error
anywhere. The sibling endpoint `send` answers 503 when it has no Redis.

The input is real: the Redis client raises redis' own ConnectionError, as a
dropped Redis does.
"""
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
import redis
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import internal_crm
from app.services import handover, user_store as user_store_module, whatsapp
from app.services.user_store import user_store

SECRET = "repro-send-secret"
NOW = int(time.time())
PHONE = "60123456789"


class FlakyRedis:
    """A dict-backed Redis that can be pulled out from under the caller."""

    def __init__(self):
        self.data = {}
        self.down = False

    def _check(self):
        if self.down:
            raise redis.exceptions.ConnectionError("Error 111 connecting to infra_redis:6379. Connection refused.")

    def get(self, key):
        self._check()
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        self._check()
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key):
        self._check()
        self.data.pop(key, None)


@pytest.fixture
def flaky():
    fake = FlakyRedis()
    user_store.reset()
    with patch.object(user_store, "_url", "redis://infra_redis:6379/3"), \
            patch.object(user_store, "_client_factory", lambda url: fake), \
            patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(settings, "crm_events_enabled", False), \
            patch.object(internal_crm, "_now", lambda: NOW), \
            patch.object(whatsapp, "send_raw", side_effect=AssertionError("a hand-back sends nothing")):
        yield fake
    user_store.reset()


def _post(client):
    body = json.dumps({
        "request_id": "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d",
        "visitor": {"phone": PHONE, "bsuid": None},
        "agent": {"id": "user-9", "name": "Manager Lim"},
    }).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), f"{NOW}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post("/internal/crm/handback", content=body, headers={
        "Content-Type": "application/json", "X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": signature,
    })


def test_handback_during_a_redis_blip_does_not_claim_nobody_held_the_visitor(flaky):
    profile = user_store.get_or_create(PHONE)
    profile.bot_id = "retail"
    user_store.save(profile)
    handover.begin(user_store.get(PHONE))
    assert handover.active(user_store.get(PHONE)), "precondition: the visitor is held, in Redis"

    flaky.down = True
    response = _post(TestClient(app))
    flaky.down = False

    # Back up: the visitor is still held -- the hand-back did not happen.
    user_store_module.user_store._offline_until = 0.0
    still_held = handover.active(user_store.get(PHONE))
    assert still_held, "precondition: nothing ended the takeover"

    assert not (response.status_code == 200 and response.json().get("result") == "not_active"), (
        f"held visitor reported as not held during a Redis outage: "
        f"{response.status_code} {response.json()}"
    )
