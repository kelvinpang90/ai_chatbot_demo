"""The CRM event queue (task 40.1): switch, shape, signature, order, failures.

A stand-in Redis and httpx.MockTransport throughout -- nothing here reaches a
real Redis or a real CRM. The signature is recomputed in the test from the
contract's own words rather than by calling the module's signer, so a signer
that signs the wrong bytes cannot agree with itself.
"""
import hashlib
import hmac
import json
import threading
import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import crm_events

SECRET = "test-secret-not-a-real-one"


class FakeRedis:
    """Just enough Redis for two lists, with a call log and a fail switch."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.calls: list[str] = []
        self.fail = False

    def _check(self, name):
        self.calls.append(name)
        if self.fail:
            raise ConnectionError("redis is down")

    def rpush(self, key, value):
        self._check("rpush")
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lindex(self, key, index):
        self._check("lindex")
        items = self.lists.get(key, [])
        return items[index] if -len(items) <= index < len(items) else None

    def lpop(self, key):
        self._check("lpop")
        items = self.lists.get(key, [])
        return items.pop(0) if items else None

    def queue(self) -> list[str]:
        return self.lists.get(crm_events.QUEUE_KEY, [])

    def dead(self) -> list[str]:
        return self.lists.get(crm_events.DEAD_KEY, [])


class Clock:
    def __init__(self, at: float = 1_760_000_000.0):
        self.at = at

    def __call__(self) -> float:
        return self.at


@pytest.fixture(autouse=True)
def _fresh_module():
    crm_events.reset()
    yield
    crm_events.reset()


@pytest.fixture
def fake(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(crm_events, "_client_factory", lambda url: redis)
    return redis


@pytest.fixture
def clock(monkeypatch):
    now = Clock()
    monkeypatch.setattr(crm_events, "_now", now)
    return now


@pytest.fixture
def switched_on():
    with patch.object(settings, "crm_events_enabled", True), \
            patch.object(settings, "redis_url", "redis://stand-in:6379/16"), \
            patch.object(settings, "crm_events_secret", SECRET):
        yield


class Crm:
    """A CRM that answers from a script, and remembers every request it saw."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else 200
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        if answer == 200:
            return httpx.Response(200, json={"result": "stored"})
        return httpx.Response(answer, text=f"status {answer}")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def event_ids(self) -> list[str]:
        return [json.loads(r.content)["event_id"] for r in self.requests]


def _someone():
    return crm_events.visitor("60123456789", "MY.abc123", "Aisha")


def _queued(fake) -> list[dict]:
    return [json.loads(raw) for raw in fake.queue()]


# --- the switch --------------------------------------------------------------


def test_switched_off_enqueue_never_touches_redis(fake):
    made = []
    with patch.object(crm_events, "_client_factory", lambda url: made.append(url) or fake):
        crm_events.enqueue("customer_message", _someone(), message={"wa_message_id": "w1", "body": "hi"})
    assert made == []
    assert fake.calls == []


def test_switched_off_start_starts_no_thread(caplog):
    with caplog.at_level("INFO"):
        assert crm_events.start() is None
    assert not [t for t in threading.enumerate() if t.name == "crm-events"]
    assert "crm events off" in caplog.text


@pytest.mark.parametrize(
    "missing, value",
    [("crm_events_secret", ""), ("redis_url", "")],
)
def test_switched_on_without_what_it_needs_counts_as_off(switched_on, fake, caplog, missing, value):
    with patch.object(settings, missing, value):
        with caplog.at_level("ERROR"):
            assert crm_events.start() is None
        crm_events.enqueue("customer_message", _someone(), message={"wa_message_id": "w1", "body": "hi"})
    assert missing.upper() in caplog.text
    assert [r.levelname for r in caplog.records if r.name == crm_events.__name__] == ["ERROR"]
    assert fake.calls == []
    assert not [t for t in threading.enumerate() if t.name == "crm-events"]


def test_switched_on_start_runs_the_consumer_on_a_daemon_thread(switched_on):
    ran = threading.Event()
    with patch.object(crm_events, "run_forever", ran.set):
        thread = crm_events.start()
        assert ran.wait(2)
    assert thread is not None and thread.daemon and thread.name == "crm-events"


def test_the_app_starts_the_queue_on_startup():
    from app.main import app

    with patch.object(crm_events, "start") as start:
        with TestClient(app):
            pass
    start.assert_called_once()


# --- the event ---------------------------------------------------------------


def test_an_event_has_the_contracts_common_shape(switched_on, fake, clock):
    crm_events.enqueue(
        "customer_message", _someone(), message={"wa_message_id": "wamid.1", "body": "Hello 你好"}
    )

    (event,) = _queued(fake)
    assert uuid.UUID(event["event_id"]).version == 4
    assert event["type"] == "customer_message"
    assert event["occurred_at"] == "2025-10-09T08:53:20Z"
    assert event["visitor"] == {"phone": "60123456789", "bsuid": "MY.abc123", "profile_name": "Aisha"}
    assert event["message"] == {"wa_message_id": "wamid.1", "body": "Hello 你好"}


def test_occurred_at_can_be_when_it_happened_rather_than_now(switched_on, fake, clock):
    crm_events.enqueue("customer_message", _someone(), occurred_at=1_700_000_000, message={})
    assert _queued(fake)[0]["occurred_at"] == "2023-11-14T22:13:20Z"


def test_a_visitor_with_only_a_bsuid_has_no_phone(switched_on, fake):
    crm_events.enqueue("customer_message", crm_events.visitor(None, "MY.abc123", None), message={})
    assert _queued(fake)[0]["visitor"] == {"phone": None, "bsuid": "MY.abc123", "profile_name": None}


def test_a_bsuid_given_as_the_number_is_filed_as_a_bsuid():
    assert crm_events.visitor("US.13491208655302741918", None, "") == {
        "phone": None,
        "bsuid": "US.13491208655302741918",
        "profile_name": None,
    }


def test_a_visitor_with_neither_is_not_queued(switched_on, fake, caplog):
    with caplog.at_level("ERROR"):
        crm_events.enqueue("customer_message", crm_events.visitor("", None, "Aisha"), message={})
    assert fake.queue() == []
    assert "neither a phone nor a bsuid" in caplog.text


def test_a_redis_that_fails_on_write_does_not_raise(switched_on, fake, caplog):
    fake.fail = True
    with caplog.at_level("ERROR"):
        crm_events.enqueue("customer_message", _someone(), message={})
    assert "could not queue" in caplog.text


def test_after_a_failed_write_redis_is_left_alone_for_a_while(switched_on, fake, clock, caplog):
    """A Redis that is down costs its timeout once, not once per event: one reply
    queues an event between each of its messages (task 40.2 cold review)."""
    fake.fail = True
    crm_events.enqueue("customer_message", _someone(), message={})
    assert fake.calls == ["rpush"]

    clock.at += crm_events.REDIS_RETRY_AFTER_SECONDS - 1
    with caplog.at_level("ERROR"):
        crm_events.enqueue("ai_reply", _someone(), message={})
    assert fake.calls == ["rpush"]
    assert "dropped a ai_reply event" in caplog.text

    fake.fail = False
    clock.at += 1
    crm_events.enqueue("ai_reply", _someone(), message={"body": "back"})
    assert fake.calls == ["rpush", "rpush"]
    assert [json.loads(raw)["message"] for raw in fake.queue()] == [{"body": "back"}]


def test_a_redis_that_cannot_even_be_created_does_not_raise(switched_on, monkeypatch):
    def explode(url):
        raise ValueError("bad url")

    monkeypatch.setattr(crm_events, "_client_factory", explode)
    crm_events.enqueue("customer_message", _someone(), message={})


# --- the signature -----------------------------------------------------------


def test_the_signature_is_over_the_send_time_and_the_exact_stored_bytes(switched_on, fake, clock):
    crm_events.enqueue("customer_message", _someone(), message={"wa_message_id": "w1", "body": "Saya nak beli 手机"})
    stored = fake.queue()[0]
    # Queued, then the CRM is unreachable for a while: past the CRM's 300-second
    # window measured from the moment it was queued.
    clock.at += 400
    crm = Crm(200)

    assert crm_events.deliver_one(fake, crm.client()) == crm_events.DELIVERED

    (request,) = crm.requests
    assert request.content == stored.encode("utf-8")
    timestamp = request.headers["X-Acuven-Timestamp"]
    assert timestamp == str(int(clock.at))
    expected = hmac.new(SECRET.encode(), f"{timestamp}.".encode() + stored.encode("utf-8"), hashlib.sha256)
    assert request.headers["X-Acuven-Signature"] == "sha256=" + expected.hexdigest()
    assert request.headers["Content-Type"] == "application/json"
    assert str(request.url) == settings.crm_events_url


# --- order -------------------------------------------------------------------


def test_nothing_behind_the_head_is_sent_until_the_head_gets_through(switched_on, fake):
    for body in ("A", "B", "C"):
        crm_events.enqueue("customer_message", _someone(), message={"wa_message_id": body, "body": body})
    a, b, c = (event["event_id"] for event in _queued(fake))
    crm = Crm(503, 503, 200, 200, 200)
    http = crm.client()

    assert crm_events.deliver_one(fake, http) == crm_events.RETRY
    assert crm_events.deliver_one(fake, http) == crm_events.RETRY
    assert crm.event_ids() == [a, a]
    while crm_events.deliver_one(fake, http) != crm_events.EMPTY:
        pass

    assert crm.event_ids() == [a, a, a, b, c]
    assert fake.queue() == []


# --- what the CRM says -------------------------------------------------------


def test_a_200_takes_the_event_off_the_queue(switched_on, fake):
    crm_events.enqueue("customer_message", _someone(), message={})
    assert crm_events.deliver_one(fake, Crm(200).client()) == crm_events.DELIVERED
    assert fake.queue() == []


def test_a_200_with_a_result_nobody_agreed_on_still_dequeues_but_warns(switched_on, fake, caplog):
    crm_events.enqueue("customer_message", _someone(), message={})
    odd = httpx.Response(200, json={"result": "filed-somewhere"})
    with caplog.at_level("WARNING"):
        assert crm_events.deliver_one(fake, Crm(odd).client()) == crm_events.DELIVERED
    assert fake.queue() == []
    assert "filed-somewhere" in caplog.text


def test_a_422_goes_to_the_dead_letters_and_the_next_event_carries_on(switched_on, fake, clock, caplog):
    crm_events.enqueue("customer_message", _someone(), message={"body": "bad"})
    crm_events.enqueue("customer_message", _someone(), message={"body": "good"})
    bad, good = fake.queue()
    crm = Crm(httpx.Response(422, text="x" * 1000), 200)
    http = crm.client()

    with caplog.at_level("ERROR"):
        assert crm_events.deliver_one(fake, http) == crm_events.DEAD
    assert crm_events.deliver_one(fake, http) == crm_events.DELIVERED

    assert fake.queue() == []
    assert [r.content.decode() for r in crm.requests] == [bad, good]
    (dead,) = [json.loads(raw) for raw in fake.dead()]
    assert dead["event"] == bad
    assert dead["status"] == 422
    assert dead["response"] == "x" * 500
    assert dead["failed_at"] == "2025-10-09T08:53:20Z"
    assert "malformed" in caplog.text


@pytest.mark.parametrize(
    "answer",
    [
        401,
        503,
        500,
        404,
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
    ],
    ids=["401", "503", "500", "404", "connect-error", "timeout"],
)
def test_anything_else_leaves_the_event_at_the_head(switched_on, fake, answer):
    crm_events.enqueue("customer_message", _someone(), message={})
    before = list(fake.queue())

    assert crm_events.deliver_one(fake, Crm(answer).client()) == crm_events.RETRY

    assert fake.queue() == before
    assert fake.dead() == []


def test_a_401_says_to_check_the_secret(switched_on, fake, caplog):
    crm_events.enqueue("customer_message", _someone(), message={})
    with caplog.at_level("ERROR"):
        crm_events.deliver_one(fake, Crm(401).client())
    assert "CRM_EVENTS_SECRET" in caplog.text


def test_failures_alert_at_once_then_every_ten_minutes_then_say_when_they_stop(switched_on, fake, clock, caplog):
    crm_events.enqueue("customer_message", _someone(), message={})
    crm = Crm(503, 503, 503, 200)
    http = crm.client()

    def errors():
        return [r for r in caplog.records if r.name == crm_events.__name__ and r.levelname == "ERROR"]

    with caplog.at_level("INFO"):
        crm_events.deliver_one(fake, http)
        assert len(errors()) == 1
        clock.at += crm_events.ALERT_EVERY_SECONDS - 1
        crm_events.deliver_one(fake, http)
        assert len(errors()) == 1
        clock.at += 1
        crm_events.deliver_one(fake, http)
        assert len(errors()) == 2
        crm_events.deliver_one(fake, http)
    assert "delivering again after 3 failed attempts" in caplog.text


# --- backoff and the loop ----------------------------------------------------


def test_backoff_doubles_from_two_caps_at_three_hundred_and_resets():
    backoff = crm_events.Backoff()
    assert [backoff.failed() for _ in range(10)] == [2, 4, 8, 16, 32, 64, 128, 256, 300, 300]
    backoff.reset()
    assert backoff.failed() == 2


class Stop(BaseException):
    """Ends `run_forever` from inside its sleep. Not an Exception, so the loop's own catch-all lets it out."""


def _sleeper(limit):
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) >= limit:
            raise Stop

    return slept, sleep


def test_the_loop_backs_off_on_failure_resets_on_success_and_idles_when_empty(switched_on, fake):
    crm_events.enqueue("customer_message", _someone(), message={"body": "A"})
    crm_events.enqueue("customer_message", _someone(), message={"body": "B"})
    crm = Crm(503, 503, 200, 503, 200)
    slept, sleep = _sleeper(limit=4)

    with pytest.raises(Stop):
        crm_events.run_forever(fake, crm.client(), sleep)

    assert slept == [2, 4, 2, crm_events.IDLE_POLL_SECONDS]
    assert fake.queue() == []


def test_the_loop_survives_a_redis_that_breaks(switched_on, fake):
    fake.fail = True
    slept, sleep = _sleeper(limit=3)

    with pytest.raises(Stop):
        crm_events.run_forever(fake, Crm().client(), sleep)

    assert slept == [2, 4, 8]
