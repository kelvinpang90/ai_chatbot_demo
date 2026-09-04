"""The customer profile store, against a stand-in Redis.

The stand-in is deliberately tiny -- get/set/delete with an expiry -- rather than
a real server or a fake library. What has to be asserted here is the contract
this module relies on (a value comes back as it went in, `ex` is reset on every
write) and, more importantly, what happens when the server is not there at all.
"""
import json
import time
from unittest.mock import patch

import pytest

from app.config import settings
from app.services import user_store as us
from app.services.user_store import (
    KEY_PREFIX,
    RETRY_AFTER_SECONDS,
    Message,
    UserStore,
)
from app.session_store import MAX_HISTORY_MESSAGES


class FakeRedis:
    """Just enough Redis: string values with an expiry, and a fail switch."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}
        self.fail = False
        self.calls = 0

    def _check(self):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis is down")

    def get(self, key):
        self._check()
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self._check()
        self.values[key] = value
        self.expiries[key] = ex

    def delete(self, key):
        self._check()
        self.values.pop(key, None)
        self.expiries.pop(key, None)


@pytest.fixture
def fake():
    return FakeRedis()


@pytest.fixture
def store(fake):
    return UserStore("redis://stand-in:6379/0", client_factory=lambda url: fake)


def test_save_then_read_back_every_field(store):
    profile = store.get_or_create("+60 17-394 8123")
    profile.bot_id = "retail"
    profile.display_name = "Tan"
    profile.language = "zh"
    profile.erp_customer_id = "CUST-42"
    profile.crm_contact_id = "17"
    profile.profile["retail"] = {"address": "12 Jalan Bukit"}
    profile.add_message("user", "有没有电饭锅")
    store.save(profile)

    fetched = store.get("+60 17-394 8123")
    assert fetched.bot_id == "retail"
    assert fetched.display_name == "Tan"
    assert fetched.language == "zh"
    assert fetched.erp_customer_id == "CUST-42"
    assert fetched.crm_contact_id == "17"
    assert fetched.profile["retail"] == {"address": "12 Jalan Bukit"}
    assert fetched.history == [Message(role="user", content="有没有电饭锅")]


def test_unknown_number_reads_as_none(store):
    assert store.get("+60111222333") is None


def test_get_or_create_writes_nothing_until_save(store, fake):
    store.get_or_create("+60111222333")
    assert fake.values == {}
    assert store.get("+60111222333") is None


def test_one_number_written_three_ways_is_one_record(store, fake):
    """The web chat types what a person would; WhatsApp sends bare digits."""
    profile = store.get_or_create("60173948123")
    profile.display_name = "Tan"
    store.save(profile)

    assert store.get("+60 17-394 8123").display_name == "Tan"
    assert store.get("(60) 173-948123").display_name == "Tan"
    assert list(fake.values) == [f"{KEY_PREFIX}60173948123"]


def test_a_blank_number_is_refused_rather_than_shared(store):
    """Everyone filing into one key would show a stranger someone's chat."""
    with pytest.raises(ValueError):
        store.get("")
    with pytest.raises(ValueError):
        store.get_or_create("   ")


def test_history_keeps_the_same_window_as_the_session(store):
    profile = store.get_or_create("+60111222333")
    for i in range(MAX_HISTORY_MESSAGES + 5):
        profile.add_message("user", f"msg-{i}")
    store.save(profile)

    history = store.get("+60111222333").history
    assert len(history) == MAX_HISTORY_MESSAGES
    assert history[0].content == "msg-5"
    assert history[-1].content == f"msg-{MAX_HISTORY_MESSAGES + 4}"


def test_a_mutation_without_save_is_not_kept(store):
    profile = store.get_or_create("+60111222333")
    store.save(profile)

    profile.display_name = "never saved"
    assert store.get("+60111222333").display_name is None


# --- the seven-day rolling window ---------------------------------------------


def test_save_sets_a_seven_day_expiry(store, fake):
    store.save(store.get_or_create("+60111222333"))
    assert fake.expiries[f"{KEY_PREFIX}60111222333"] == 7 * 24 * 60 * 60


def test_every_write_pushes_the_expiry_back_out(fake):
    store = UserStore("redis://stand-in", ttl_seconds=600, client_factory=lambda url: fake)
    key = f"{KEY_PREFIX}60111222333"

    profile = store.get_or_create("+60111222333")
    store.save(profile)
    fake.expiries[key] = 30  # as if most of the window had already elapsed

    store.save(profile)
    assert fake.expiries[key] == 600


def test_last_seen_moves_on_every_save(store):
    profile = store.get_or_create("+60111222333")
    profile.last_seen = 0.0
    store.save(profile)
    assert store.get("+60111222333").last_seen > 0.0


def test_first_seen_survives_later_saves(store):
    store.save(store.get_or_create("+60111222333"))
    first = store.get("+60111222333").first_seen

    later = store.get("+60111222333")
    store.save(later)
    assert store.get("+60111222333").first_seen == first


# --- degradation: none of the above may stop working when Redis does ----------


def test_profiles_still_work_with_no_redis_configured():
    store = UserStore("")
    profile = store.get_or_create("+60111222333")
    profile.display_name = "Tan"
    store.save(profile)

    assert store.get("+60111222333").display_name == "Tan"


def test_a_redis_that_refuses_connections_falls_back_to_memory():
    def explode(url):
        raise ConnectionError("no route to host")

    store = UserStore("redis://gone:6379/0", client_factory=explode)
    profile = store.get_or_create("+60111222333")
    profile.display_name = "Tan"
    store.save(profile)

    assert store.get("+60111222333").display_name == "Tan"


def test_a_redis_that_dies_mid_demo_falls_back_to_memory(store, fake):
    profile = store.get_or_create("+60111222333")
    profile.display_name = "Tan"
    store.save(profile)

    fake.fail = True
    profile.display_name = "Tan Ah Kow"
    store.save(profile)

    assert store.get("+60111222333").display_name == "Tan Ah Kow"


def test_a_dead_redis_is_not_retried_on_every_message(store, fake):
    """Otherwise every turn of the demo waits out the connect timeout."""
    fake.fail = True
    store.get("+60111222333")
    calls_after_first_failure = fake.calls

    for _ in range(5):
        store.get("+60111222333")
    assert fake.calls == calls_after_first_failure


def test_redis_is_picked_back_up_once_the_pause_is_over(store, fake):
    fake.fail = True
    store.get("+60111222333")
    fake.fail = False

    with patch.object(us.time, "time", return_value=time.time() + RETRY_AFTER_SECONDS + 1):
        store.get("+60111222333")
    assert fake.calls > 1


def test_memory_fallback_expires_on_the_same_window():
    store = UserStore("", ttl_seconds=60)
    store.save(store.get_or_create("+60111222333"))

    with patch.object(us.time, "time", return_value=time.time() + 61):
        assert store.get("+60111222333") is None


# --- records written by another build -----------------------------------------


def test_a_record_with_an_unknown_field_still_loads(store, fake):
    """A rollback should cost a field, not crash the demo mid-conversation."""
    fake.values[f"{KEY_PREFIX}60111222333"] = json.dumps(
        {"phone": "60111222333", "display_name": "Tan", "invented_by_a_later_build": 1}
    )

    fetched = store.get("+60111222333")
    assert fetched.phone == "60111222333"
    assert fetched.display_name == "Tan"


def test_an_unreadable_record_reads_as_no_record(store, fake):
    fake.values[f"{KEY_PREFIX}60111222333"] = "{not json"
    assert store.get("+60111222333") is None


def test_delete_removes_the_record(store):
    store.save(store.get_or_create("+60111222333"))
    store.delete("+60111222333")
    assert store.get("+60111222333") is None


def test_the_module_level_store_reads_its_url_from_settings():
    assert isinstance(us.user_store, UserStore)
    assert us.user_store._url == settings.redis_url


def test_profile_slots_are_per_bot(store):
    profile = store.get_or_create("+60111222333")
    profile.profile["retail"] = {"address": "12 Jalan Bukit"}
    profile.profile["food"] = {"spice": "extra"}
    store.save(profile)

    fetched = store.get("+60111222333")
    assert fetched.profile == {
        "retail": {"address": "12 Jalan Bukit"},
        "food": {"spice": "extra"},
    }
