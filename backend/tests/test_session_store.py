from app.session_store import MAX_HISTORY_MESSAGES, SessionStore


def test_get_or_create_then_read_back():
    store = SessionStore(daily_msg_limit=100)
    session = store.get_or_create("session-1")
    session.bot_id = "retail"
    session.add_message("user", "hello")

    fetched = store.get("session-1")
    assert fetched is session
    assert fetched.bot_id == "retail"
    assert fetched.history[0].role == "user"
    assert fetched.history[0].content == "hello"


def test_get_returns_none_for_unknown_key():
    store = SessionStore(daily_msg_limit=100)
    assert store.get("nope") is None


def test_history_truncates_to_max_messages():
    store = SessionStore(daily_msg_limit=100)
    session = store.get_or_create("session-2")
    for i in range(MAX_HISTORY_MESSAGES + 10):
        session.add_message("user", f"msg-{i}")

    assert len(session.history) == MAX_HISTORY_MESSAGES
    assert session.history[-1].content == f"msg-{MAX_HISTORY_MESSAGES + 9}"
    assert session.history[0].content == "msg-10"


def test_reset_clears_bot_and_history():
    store = SessionStore(daily_msg_limit=100)
    session = store.get_or_create("session-3")
    session.bot_id = "hotel"
    session.add_message("user", "hi")

    store.reset("session-3")

    assert session.bot_id is None
    assert session.history == []


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
