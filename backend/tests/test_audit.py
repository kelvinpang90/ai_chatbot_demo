"""The audit log: what reaches MySQL, and what happens when MySQL is not there.

Every test here drives a real `AuditStore` against a fake DB-API connection, so
the SQL and the parameter tuples are asserted as written rather than mocked away.
What that cannot check is whether MySQL accepts the statements -- that is the
live run recorded in tasks/todo.md, against a real mysql:8 container.
"""
import os
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import HandoverReplyRequest, HandoverRequest
from app.routers.console import reply_as_human, set_handover
from app.routers.whatsapp_webhook import dispatch_message
from app.services import audit, crm_events, handover, llm, transcribe, whatsapp_media
from app.services.audit import AuditStore, Turn
from app.services.user_store import UserProfile, user_store

URL = "mysql://demo:pw@db:3306/ai_chatbot"


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.lastrowid = 0

    def execute(self, sql, params=None):
        if self._conn.fail_on and self._conn.fail_on in sql:
            raise RuntimeError("the database said no")
        self._conn.statements.append((" ".join(sql.split()), params))
        # Only an insert produces a row id, so the schema statements do not shift
        # the numbers the association tests assert on.
        if sql.lstrip().upper().startswith("INSERT"):
            self._conn.next_id += 1
            self.lastrowid = self._conn.next_id

    def fetchall(self):
        return self._conn.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    """Enough of PyMySQL to hold the store to its contract."""

    def __init__(self, fail_on: str | None = None):
        self.statements: list[tuple[str, tuple]] = []
        self.rows: list[dict] = []
        self.next_id = 0
        self.fail_on = fail_on
        self.pings = 0

    def cursor(self, *args, **kwargs):
        return FakeCursor(self)

    def ping(self, reconnect=False):
        self.pings += 1

    def writes(self, table: str) -> list[tuple[str, tuple]]:
        return [(sql, params) for sql, params in self.statements if f"INTO {table}" in sql]


def _store(conn=None, url: str = URL, **kwargs):
    conn = conn or FakeConnection(**kwargs)
    return AuditStore(url, connect=lambda dsn: conn), conn


def _turn(**kwargs) -> Turn:
    base = {
        "conversation_id": "c-1",
        "key_id": "60173948123",
        "channel": audit.WHATSAPP,
        "bot_id": "retail",
    }
    return Turn(**{**base, **kwargs})


# --- the connection string ---------------------------------------------------
# Parsing it lives in test_mysql_url.py, shared with the verticals store.


def test_a_malformed_url_is_not_retried():
    """A typo will not fix itself in thirty seconds; do not pay for it every message."""
    store, conn = _store(url="postgres://u:p@host/db")
    for _ in range(3):
        store.record_message(turn=_turn(), role="user", content="hi")
    assert conn.statements == []


def test_an_empty_url_means_the_log_is_off():
    store, conn = _store(url="")
    assert store.enabled is False
    store.record_message(turn=_turn(), role="user", content="hi")
    assert conn.statements == []


# --- writing -----------------------------------------------------------------


def test_the_schema_is_created_once_not_per_write():
    store, conn = _store()
    store.record_message(turn=_turn(), role="user", content="one")
    store.record_message(turn=_turn(), role="user", content="two")
    creates = [sql for sql, _ in conn.statements if sql.startswith("CREATE TABLE")]
    assert len(creates) == len(audit.SCHEMA)


def test_a_message_is_written_with_its_whole_turn():
    store, conn = _store()
    row_id = store.record_message(
        turn=_turn(), role="user", content="ada stock?", source=audit.VOICE
    )
    sql, params = conn.writes("chat_messages")[0]
    assert params[:7] == ("c-1", "60173948123", "whatsapp", "retail", "user", "ada stock?", "voice")
    assert row_id is not None


def test_a_tool_call_hangs_off_the_message_being_answered():
    store, conn = _store()
    turn = _turn()
    turn.message_id = 41
    store.record_tool_call(
        turn=turn,
        tool="erp_search_sku",
        tool_use_id="tu_1",
        input={"term": "earbuds"},
        output="[]",
        duration_ms=201,
        status="ok",
    )
    _, params = conn.writes("tool_calls")[0]
    assert params[2] == 41
    assert params[3] == "erp_search_sku"
    assert params[5] == '{"term": "earbuds"}'
    assert params[7:9] == (201, "ok")


def test_tool_input_that_will_not_serialise_costs_its_column_not_its_row():
    store, conn = _store()
    store.record_tool_call(
        turn=_turn(),
        tool="t",
        tool_use_id="tu",
        input={"when": object()},
        output=None,
        duration_ms=None,
        status="ok",
    )
    rows = conn.writes("tool_calls")
    assert len(rows) == 1, "the call still has to be recorded"
    # `default=str` catches almost everything, which is the point: the row
    # survives either way.
    assert rows[0][1][5] is not None


def test_usage_is_written_with_what_the_call_cost():
    store, conn = _store()
    store.record_usage(
        turn=_turn(),
        model="claude-opus-5",
        input_tokens=1200,
        output_tokens=300,
        cache_write_tokens=1097,
        cache_read_tokens=0,
        cost_myr=0.0421,
    )
    _, params = conn.writes("model_usage")[0]
    assert params[4:10] == ("claude-opus-5", 1200, 300, 1097, 0, 0.0421)


def test_long_content_is_truncated_not_dropped():
    store, conn = _store()
    store.record_message(turn=_turn(), role="assistant", content="x" * 200_000)
    _, params = conn.writes("chat_messages")[0]
    assert len(params[5]) == audit.MAX_CONTENT_CHARS


def test_the_connection_is_pinged_so_an_idle_night_does_not_cost_a_row():
    store, conn = _store()
    store.record_message(turn=_turn(), role="user", content="hi")
    store.record_message(turn=_turn(), role="user", content="hi again")
    assert conn.pings == 2


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is POSIX only")
def test_a_row_is_stamped_in_the_container_s_local_time():
    """Both compose files set TZ=Asia/Kuala_Lumpur, and this is what depends on it.

    A DATETIME column stores no timezone, so if this ever went back to UTC every
    stored row would be eight hours off with nothing in the value to say so --
    and a demo run at 9pm would be filed, and searched for, under 13:00.
    """
    moment = 1789000000.0  # 2026-09-10 00:26:40 UTC

    def stamp_under(tz: str) -> str:
        with patch.dict(os.environ, {"TZ": tz}):
            time.tzset()
            return audit._timestamp(moment)

    try:
        kl = stamp_under("Asia/Kuala_Lumpur")
        utc = stamp_under("UTC")
    finally:
        time.tzset()  # back to however this process was started

    assert kl.startswith("2026-09-10 08:26:40"), kl
    assert utc.startswith("2026-09-10 00:26:40"), utc


def test_the_millisecond_survives():
    """DATETIME(3) is worth having only if the fraction actually gets there."""
    assert audit._timestamp(1789000000.938).endswith(".938")


# --- failing -----------------------------------------------------------------


def test_a_failed_write_is_dropped_rather_than_raised():
    store, _ = _store(fail_on="INTO chat_messages")
    assert store.record_message(turn=_turn(), role="user", content="hi") is None


def test_a_failure_opens_the_circuit_for_half_a_minute():
    """Otherwise every message pays the connect timeout while MySQL is down."""
    attempts = []

    def connect(dsn):
        attempts.append(dsn)
        raise RuntimeError("no route to host")

    store = AuditStore(URL, connect=connect)
    for _ in range(5):
        store.record_message(turn=_turn(), role="user", content="hi")
    assert len(attempts) == 1

    with patch("app.services.audit.time.time", return_value=9e9):
        store.record_message(turn=_turn(), role="user", content="hi")
    assert len(attempts) == 2


def test_there_is_no_memory_fallback():
    """An audit row kept in memory is a record that will be lost while looking kept.

    This is the one place the audit log deliberately behaves unlike the user
    store, so it is asserted rather than left to the docstring.
    """
    store = AuditStore(URL, connect=lambda dsn: (_ for _ in ()).throw(RuntimeError("down")))
    store.record_message(turn=_turn(), role="user", content="hi")
    assert store.query("SELECT 1") == []


def test_reading_back_returns_rows():
    store, conn = _store()
    conn.rows = [{"id": 1, "content": "hi"}]
    assert store.query("SELECT * FROM chat_messages") == [{"id": 1, "content": "hi"}]


# --- the turn in flight ------------------------------------------------------


def test_recording_outside_a_turn_does_nothing():
    store, conn = _store()
    with patch.object(audit, "audit_store", store):
        audit.record_message("user", "nobody opened a turn")
        audit.record_tool_call(tool="t", tool_use_id="tu")
        audit.record_usage(
            model="m",
            input_tokens=1,
            output_tokens=1,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost_myr=0.0,
        )
    assert conn.statements == []


def test_a_message_id_is_carried_to_the_tool_calls_it_caused():
    store, conn = _store()
    with patch.object(audit, "audit_store", store):
        audit.begin(conversation_id="c-1", key_id="60173948123", channel="web", bot_id="retail")
        audit.record_message("user", "ada stock?")
        audit.record_tool_call(tool="erp_search_sku", tool_use_id="tu_1")
        audit.close()
    assert conn.writes("tool_calls")[0][1][2] == 1, "the tool call belongs to message 1"


def test_begin_for_mints_an_id_for_a_profile_that_predates_the_audit_log():
    """Records written before this feature are live in Redis for seven days."""
    profile = UserProfile(key_id="60173948123", bot_id="retail")
    assert profile.conversation_id is None
    audit.begin_for(profile, audit.WEB)
    assert profile.conversation_id
    assert audit.current().conversation_id == profile.conversation_id
    audit.close()


def test_begin_for_keeps_an_id_the_profile_already_has():
    profile = UserProfile(key_id="60173948123", bot_id="retail", conversation_id="c-existing")
    audit.begin_for(profile, audit.WEB)
    assert audit.current().conversation_id == "c-existing"
    audit.close()


def test_a_customer_with_no_bot_yet_still_opens_a_turn():
    profile = UserProfile(key_id="60173948123")
    audit.begin_for(profile, audit.WEB)
    assert audit.current().bot_id == ""
    audit.close()


# --- both channels, end to end -----------------------------------------------
#
# The unit tests above prove the store writes what it is told. These prove the
# two channels tell it anything at all -- the failure the rest of this file
# cannot see is a perfectly correct audit log that nothing ever calls.


@pytest.fixture
def recording():
    """The shared audit log, pointed at a fake connection for the whole request."""
    store, conn = _store()
    with patch.object(audit, "audit_store", store):
        yield conn


@contextmanager
def _a_reply(text: str = "We have 47 in stock."):
    with patch.object(llm, "get_reply", return_value=text):
        yield


@contextmanager
def _operator():
    """The web chat takes the console token since task 29.1."""
    with patch.object(settings, "console_token", "t"):
        with TestClient(app, headers={"X-Console-Token": "t"}) as http:
            yield http


def test_a_web_exchange_is_recorded_from_both_sides(recording):
    with _operator() as http:
        http.post("/api/chat/identify", json={"phone": "017-394 8123", "lang": "en"})
        http.post("/api/chat/60173948123/select", json={"bot_id": "retail", "lang": "en"})
        with _a_reply():
            http.post("/api/chat/60173948123/message", json={"message": "ada stock?"})

    rows = [params for _sql, params in recording.writes("chat_messages")]
    # The greeting, then the customer, then the bot.
    assert [(p[4], p[5]) for p in rows][1:] == [
        ("user", "ada stock?"),
        ("assistant", "We have 47 in stock."),
    ]
    assert all(p[2] == "web" for p in rows)
    assert len({p[0] for p in rows}) == 1, "one conversation id across the exchange"


def test_picking_a_second_demo_starts_a_second_transcript(recording):
    with _operator() as http:
        http.post("/api/chat/identify", json={"phone": "60173948123", "lang": "en"})
        http.post("/api/chat/60173948123/select", json={"bot_id": "retail", "lang": "en"})
        http.post("/api/chat/60173948123/select", json={"bot_id": "hotel", "lang": "en"})

    conversations = {params[0] for _sql, params in recording.writes("chat_messages")}
    assert len(conversations) == 2


def test_a_whatsapp_exchange_is_recorded_against_the_phone_number(recording):
    profile = user_store.get_or_create("60173948123")
    profile.bot_id = "retail"
    user_store.save(profile)

    with _a_reply():
        dispatch_message(
            {"id": "wamid.text", "from": "60173948123", "type": "text", "text": {"body": "ada stock?"}}
        )

    rows = [params for _sql, params in recording.writes("chat_messages")]
    assert [(p[1], p[2], p[4], p[6]) for p in rows] == [
        ("60173948123", "whatsapp", "user", "text"),
        ("60173948123", "whatsapp", "assistant", "text"),
    ]


def test_a_voice_note_is_recorded_as_spoken_not_typed(recording):
    """The transcript is plain text by the time it is stored, so the column is
    the only thing that still knows the customer spoke -- which is half of what
    task 36 exists to demonstrate."""
    profile = user_store.get_or_create("60173948123")
    profile.bot_id = "retail"
    user_store.save(profile)

    media = whatsapp_media.Media(content=b"OggS-pretend-opus", mime_type="audio/ogg; codecs=opus")
    with _a_reply(), patch.object(
        whatsapp_media, "fetch_media", return_value=media
    ), patch.object(transcribe, "transcribe", return_value="ada stock?"):
        dispatch_message(
            {"id": "wamid.voice", "from": "60173948123", "type": "audio", "audio": {"id": "media-1"}}
        )

    rows = [params for _sql, params in recording.writes("chat_messages")]
    assert [(p[4], p[5], p[6]) for p in rows][0] == ("user", "ada stock?", "voice")


def test_tapping_a_product_off_the_list_is_recorded_as_a_tap(recording):
    profile = user_store.get_or_create("60173948123")
    profile.bot_id = "retail"
    user_store.save(profile)

    with _a_reply():
        dispatch_message(
            {
                "id": "wamid.t",
                "from": "60173948123",
                "type": "interactive",
                "interactive": {
                    "type": "list_reply",
                    "list_reply": {"id": "qq:0", "title": "Do you deliver?"},
                },
            }
        )

    rows = [params for _sql, params in recording.writes("chat_messages")]
    assert rows and rows[0][6] == "interactive"


# --- the menu stage (task 43) ------------------------------------------------
#
# A customer who has not picked a demo is answered with the demo list. Until
# task 43 that exchange was never written down, so the console's copy of a
# conversation lost every line between a hand-back and the next pick, while the
# phone and the CRM's inbox both had them.

MENU_LINE = "[list] 欢迎！想试哪一种 AI 客服？\nWelcome! Which AI assistant would you like to try?"


def _says(phone: str, body: str, seq: int) -> dict:
    return {"id": f"wamid.menu-stage.{seq}", "from": phone, "type": "text", "text": {"body": body}}


def _console_reply(phone: str, text: str) -> None:
    with patch.object(whatsapp_media, "send_message"):
        reply_as_human(HandoverReplyRequest(key_id=phone, text=text))


def _console_holds(phone: str, active: bool) -> None:
    set_handover(HandoverRequest(key_id=phone, active=active))


def _chat_rows(recording) -> list[tuple]:
    return [params for _sql, params in recording.writes("chat_messages")]


def test_a_customer_handed_back_before_picking_a_demo_stays_on_the_console(recording):
    """The 2026-10-21 phone run, replayed. The customer typed "1" rather than
    tapping the list, so every hand-back put them back at the menu -- and the
    console lost the four lines the phone and the CRM both showed."""
    phone = "60173948123"
    dispatch_message(_says(phone, "转人工", 1))
    handed_over = handover.HANDED_OVER_MESSAGE.pick(user_store.get(phone).language)
    _console_reply(phone, "你好")
    dispatch_message(_says(phone, "你好", 2))
    _console_reply(phone, "你好")
    _console_holds(phone, False)
    dispatch_message(_says(phone, "1", 3))
    _console_holds(phone, True)
    _console_reply(phone, "你好")
    dispatch_message(_says(phone, "1", 4))
    _console_reply(phone, "请问有什么可以帮你")
    _console_holds(phone, False)
    dispatch_message(_says(phone, "没有了", 5))

    rows = _chat_rows(recording)
    assert [(p[4], p[5]) for p in rows] == [
        ("user", "转人工"),
        ("assistant", handed_over),
        ("assistant", "你好"),
        ("user", "你好"),
        ("assistant", "你好"),
        ("user", "1"),
        ("assistant", MENU_LINE),
        ("assistant", "你好"),
        ("user", "1"),
        ("assistant", "请问有什么可以帮你"),
        ("user", "没有了"),
        ("assistant", MENU_LINE),
    ]
    assert len({p[0] for p in rows}) == 1, "one conversation, as on the phone"


def test_the_menu_is_filed_as_the_line_the_crm_is_sent(recording):
    """The console and the CRM's inbox are read side by side; the same message
    must read the same in both."""
    phone = "60173948124"
    user_store.save(user_store.get_or_create(phone))

    (sent,) = dispatch_message(_says(phone, "hello", 1))

    assert _chat_rows(recording)[-1][5] == crm_events.outbound_body(sent) == MENU_LINE


def test_a_stranger_at_the_menu_still_leaves_no_transcript(recording):
    """Task 32's rule stands (Kelvin, 2026-10-21): a number that only ever saw
    the menu leaves nothing behind -- not a record, and not a conversation on the
    console either. The CRM, which is told about every message, still has it."""
    stranger = "60173948125"

    dispatch_message(_says(stranger, "hi", 1))
    dispatch_message({**_says(stranger, "", 2), "type": "sticker", "sticker": {"id": "s"}})

    assert _chat_rows(recording) == []
    assert user_store.get(stranger) is None


def test_a_known_customer_at_the_menu_who_sends_a_sticker_is_on_the_console(recording):
    phone = "60173948126"
    user_store.save(user_store.get_or_create(phone))

    dispatch_message({**_says(phone, "", 1), "type": "sticker", "sticker": {"id": "s"}})

    assert [(p[4], p[5]) for p in _chat_rows(recording)] == [
        ("user", "[sticker]"),
        ("assistant", MENU_LINE),
    ]


@pytest.mark.parametrize(
    ("bot_id", "message", "their_line", "source"),
    [
        (
            None,
            {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "gone", "title": "Old demo"}}},
            "Old demo",
            "interactive",
        ),
        (
            None,
            {"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": "{}"}}},
            "[form]",
            "interactive",
        ),
        ("a-retired-demo", {"type": "text", "text": {"body": "hello"}}, "hello", "text"),
    ],
    ids=["a list row that is no demo", "a form with no demo", "a demo retired under them"],
)
def test_every_other_way_back_to_the_menu_is_on_the_console(recording, bot_id, message, their_line, source):
    phone = "60173948128"
    profile = user_store.get_or_create(phone)
    profile.bot_id = bot_id
    user_store.save(profile)

    dispatch_message({"id": "wamid.menu-stage.1", "from": phone, **message})

    assert [(p[4], p[5], p[6]) for p in _chat_rows(recording)] == [
        ("user", their_line, source),
        ("assistant", MENU_LINE, "text"),
    ]


def test_menu_opens_a_new_transcript_that_the_demo_picked_from_it_continues(recording):
    """`menu` still starts a new conversation (2026-09-15); it now opens with the
    word that started it, and the demo picked off the list carries on in it
    rather than in a third one. What they tapped is a line of its own."""
    phone = "60173948127"
    profile = user_store.get_or_create(phone)
    profile.bot_id = "retail"
    user_store.save(profile)
    with _a_reply():
        dispatch_message(_says(phone, "ada stock?", 1))
    before = _chat_rows(recording)[0][0]

    dispatch_message(_says(phone, "menu", 2))
    dispatch_message(
        {
            "id": "wamid.menu-stage.3",
            "from": phone,
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "hotel", "title": "Hotel 酒店"},
            },
        }
    )

    after = _chat_rows(recording)[2:]
    assert [(p[4], p[5], p[6]) for p in after][:3] == [
        ("user", "menu", "text"),
        ("assistant", MENU_LINE, "text"),
        ("user", "Hotel 酒店", "interactive"),
    ]
    assert after[3][4] == "assistant", "then the hotel greeting"
    assert {p[0] for p in after} == {user_store.get(phone).conversation_id}
    assert before not in {p[0] for p in after}


def test_the_demo_still_answers_when_mysql_is_down():
    """The whole posture of this module in one test: an audit log that cannot
    write is a lost record, never a customer who got no reply."""
    down = AuditStore(URL, connect=lambda dsn: (_ for _ in ()).throw(RuntimeError("down")))
    profile = user_store.get_or_create("60173948123")
    profile.bot_id = "retail"
    user_store.save(profile)

    with patch.object(audit, "audit_store", down), _a_reply("still here"):
        payloads = dispatch_message(
            {"id": "wamid.down", "from": "60173948123", "type": "text", "text": {"body": "hi"}}
        )

    assert payloads[0]["text"]["body"] == "still here"
