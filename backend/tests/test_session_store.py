from app.session_store import SessionStore


def test_daily_rate_limit_blocks_after_threshold():
    store = SessionStore(daily_msg_limit=3)
    phone = "+60123456789"

    assert store.check_and_increment_daily_count(phone) is True
    assert store.check_and_increment_daily_count(phone) is True
    assert store.check_and_increment_daily_count(phone) is True
    assert store.check_and_increment_daily_count(phone) is False


def test_daily_rate_limit_is_per_phone_number():
    store = SessionStore(daily_msg_limit=1)
    assert store.check_and_increment_daily_count("+60111") is True
    assert store.check_and_increment_daily_count("+60222") is True
    assert store.check_and_increment_daily_count("+60111") is False


def test_message_id_dedup_detects_repeat():
    store = SessionStore(daily_msg_limit=100)
    assert store.is_duplicate_message("wamid.ABC123") is False
    assert store.is_duplicate_message("wamid.ABC123") is True
    assert store.is_duplicate_message("wamid.DEF456") is False
