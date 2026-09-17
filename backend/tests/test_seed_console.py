"""The console seed (tasks 39.1, 39.2): what it files, and what it must never touch.

The batch is built in memory and checked as data; the writing half is run
against a fake connection that records every statement. That the SQL itself
runs against MySQL 8 is the live run recorded under task 39.1 in tasks/todo.md.
"""
import json
import random
import time
from collections import Counter
from unittest.mock import patch

import pytest

from app.config import settings
from app.console import cost
from app.routers import console
from app.services import phone
from app.services.user_store import UserProfile, identity, user_store
from app.tasks import seed_console, seed_documents, seed_lines
from app.tools import local
from app.verticals.food import models as food_models
from app.verticals.hotel import models as hotel_models
from app.verticals.realestate import models as realestate_models
from app.verticals.saas import models as saas_models

NOW = time.mktime((2026, 9, 17, 3, 30, 0, 0, 0, -1))


class FakeFiler(seed_documents.Filer):
    """Hands back what the model functions would, and remembers every call."""

    def __init__(self):
        super().__init__()
        self.documents = []

    def _next(self, kind, **fields):
        self.filed += 1
        self.documents.append({"kind": kind, "id": self.filed, **fields})
        return self.filed

    def food_order(self, *, key_id, name, lines, address, fee, at):
        return self._next("food", key_id=key_id, lines=lines, fee=fee, at=at)

    def hotel_booking(self, *, key_id, name, stay, at):
        n = self._next("hotel", key_id=key_id, stay=stay, at=at)
        return hotel_models.Booking(
            id=n, booking_id=hotel_models.booking_no(n), customer_key=key_id, customer_name=name, phone="",
            status=hotel_models.CONFIRMED, booked_at="2026-09-01 10:00:00.000", **stay,
        )

    def ticket(self, *, key_id, name, subject, description, priority, at):
        n = self._next("saas", key_id=key_id, at=at)
        return saas_models.Ticket(
            id=n, ticket_id=saas_models.ticket_no(n), customer_key=key_id, customer_name=name, phone="",
            subject=subject, description=description, priority=priority, status=saas_models.OPEN,
            opened_at="2026-09-01 10:00:00.000",
        )

    def viewing(self, *, name, listing_id, viewing_date, preferred_time, at):
        n = self._next("realestate", name=name, at=at)
        return realestate_models.Viewing(
            id=n, listing_id=listing_id, customer_name=name, phone="", viewing_date=viewing_date.isoformat(),
            preferred_time=preferred_time, created_at="2026-09-01 10:00:00.000",
            area="Somewhere", property_type="Condo", price_rm=500000.0,
        )


@pytest.fixture(scope="module")
def filed():
    filer = FakeFiler()
    return seed_console.plan(NOW, random.Random(7), filer), filer


@pytest.fixture(scope="module")
def batch(filed):
    return filed[0]


def _tool_rows(conversation, tool):
    return [row for row in conversation.rows if row.kind == "tool" and row.values["tool"] == tool]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.lastrowid = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("MySQL went away")
        self.conn.statements.append((sql, params))
        self.lastrowid += 1
        return 3 if sql.startswith("DELETE") else 1


class FakeConnection:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.statements = []
        self.events = []

    def cursor(self):
        return FakeCursor(self)

    def begin(self):
        self.events.append("begin")

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


@pytest.fixture
def mysql():
    with patch.object(settings, "mysql_url", "mysql://u:p@db:3306/chat"):
        yield


# --- the batch ----------------------------------------------------------------


def test_ninety_customers_six_per_industry_and_language(batch):
    assert len(batch) == 90
    per = Counter((c.bot_id, c.language) for c in batch)
    assert set(per) == {(b, l) for b in seed_console.BOTS for l in seed_lines.LANGUAGES}
    assert set(per.values()) == {6}
    assert len({c.name for c in batch}) == 90


def test_every_key_is_a_seed_key_the_console_can_look_up(batch):
    """Filed under a key `identity()` passes through unchanged, or no name shows."""
    for customer in batch:
        assert seed_console.is_seeded(customer.key_id)
        assert phone.is_bsuid(customer.key_id)
        assert identity(customer.key_id) == customer.key_id
    assert len({c.key_id for c in batch}) == 90


def test_everything_happened_in_the_last_four_weeks_and_not_the_last_hour(batch):
    earliest = NOW - seed_console.DAYS * 86400
    latest = NOW - seed_console.QUIET_SECONDS
    for customer in batch:
        moments = [row.at for conv in customer.conversations for row in conv.rows]
        assert moments == sorted(moments)
        assert earliest < moments[0] and moments[-1] < latest + 15 * 60


def test_the_batch_is_spread_over_the_weeks_not_piled_on_one_day(batch):
    days = {int((NOW - c.conversations[-1].rows[0].at) // 86400) for c in batch}
    assert len(days) >= 15


def test_every_room_search_found_something(batch):
    """A query that matches nothing draws a card saying so, on every run."""
    calls = [row for c in batch for conv in c.conversations for row in _tool_rows(conv, "hotel_search_rooms")]
    assert calls
    for row in calls:
        assert isinstance(json.loads(row.values["output"]), list), row.values


@pytest.mark.parametrize("bot_id", seed_console.BOTS)
@pytest.mark.parametrize("language", seed_lines.LANGUAGES)
def test_every_topic_with_a_tool_finds_something(bot_id, language):
    """The whole template list, not just what one random draw happened to pick."""
    from app.bots.registry import get_bot

    for topic in seed_lines.TOPICS[bot_id][language]:
        if topic.tool:
            output = seed_console._tool_output(get_bot(bot_id), topic.tool, topic.tool_input)
            assert isinstance(json.loads(output), list), (topic.ask, output)


def test_usage_is_priced_the_way_a_live_call_is(batch):
    rows = [row for c in batch for conv in c.conversations for row in conv.rows if row.kind == "usage"]
    for row in rows:
        v = row.values
        tokens = {
            "input": v["input_tokens"],
            "output": v["output_tokens"],
            "cache_write": v["cache_write_tokens"],
            "cache_read": v["cache_read_tokens"],
        }
        assert v["cost_myr"] == cost.cost_myr(v["model"], tokens)


# --- writing it ---------------------------------------------------------------


def test_clears_only_seed_keys_then_fills_in_one_transaction(batch, mysql):
    conn = FakeConnection()
    seed_console.reseed(batch[:3], connect=lambda dsn: conn)

    deletes = [(sql, params) for sql, params in conn.statements if sql.startswith("DELETE")]
    assert [sql.split()[2] for sql, _ in deletes] == ["chat_messages", "tool_calls", "model_usage"]
    assert all(params == ("ZZ.SEED%",) for _, params in deletes)

    writes = [sql for sql, _ in conn.statements if not sql.lstrip().startswith("CREATE")]
    assert all(sql.startswith("DELETE") for sql in writes[:3])
    assert all(sql.startswith("INSERT") for sql in writes[3:])
    assert conn.events == ["begin", "commit", "close"]


def test_a_failed_insert_rolls_back_the_clear_too(batch, mysql):
    conn = FakeConnection(fail_on="INSERT INTO tool_calls")
    with pytest.raises(RuntimeError):
        seed_console.reseed(batch, connect=lambda dsn: conn)
    assert conn.events == ["begin", "rollback", "close"]
    assert user_store.everyone() == []


def test_tool_and_usage_rows_hang_off_the_customer_message(batch, mysql):
    conn = FakeConnection()
    customer = next(c for c in batch if any(r.kind == "tool" for conv in c.conversations for r in conv.rows))
    seed_console.reseed([customer], connect=lambda dsn: conn)

    attached = [
        params[2]
        for sql, params in conn.statements
        if sql.startswith("INSERT INTO tool_calls") or sql.startswith("INSERT INTO model_usage")
    ]
    assert attached and None not in attached


def test_real_customers_profiles_survive_and_seeded_ones_are_replaced(batch, mysql):
    real = UserProfile(key_id="60173948123", phone="60173948123", display_name="Real Person")
    user_store.save(real)
    stale = UserProfile(key_id="ZZ.SEED0999", user_id="ZZ.SEED0999", display_name="Old Seed")
    user_store.save(stale)

    counts = seed_console.reseed(batch[:2], connect=lambda dsn: FakeConnection())

    assert counts.cleared_profiles == 1
    assert user_store.get("60173948123").display_name == "Real Person"
    assert user_store.get("ZZ.SEED0999") is None
    assert {p.key_id for p in user_store.everyone()} == {"60173948123", batch[0].key_id, batch[1].key_id}


def test_the_console_shows_a_seeded_customer_by_name(batch, mysql):
    seed_console.reseed(batch[:1], connect=lambda dsn: FakeConnection())
    assert console._known_name(batch[0].key_id) == batch[0].name


def test_clear_files_nothing_new(batch, mysql):
    seed_console.reseed(batch[:2], connect=lambda dsn: FakeConnection())
    conn = FakeConnection()
    counts = seed_console.clear(connect=lambda dsn: conn)
    assert counts.cleared_profiles == 2
    assert not [sql for sql, _ in conn.statements if sql.startswith("INSERT")]
    assert user_store.everyone() == []


def test_a_seeded_profile_has_no_phone_to_send_to(batch, mysql):
    seed_console.reseed(batch[:1], connect=lambda dsn: FakeConnection())
    profile = user_store.get(batch[0].key_id)
    assert profile.phone is None


@pytest.mark.parametrize("missing", ["mysql_url", "redis_url", "verticals_mysql_url"])
def test_refuses_to_run_without_all_three_stores(missing, capsys):
    urls = {
        "mysql_url": "mysql://u:p@db:3306/chat",
        "redis_url": "redis://r:6379/0",
        "verticals_mysql_url": "mysql://u:p@db:3306/verticals",
    }
    urls[missing] = ""
    with patch.multiple(settings, **urls):
        assert seed_console.main([]) == 2
    assert "VERTICALS_MYSQL_URL" in capsys.readouterr().out


# --- the documents (task 39.2) --------------------------------------------------


def test_three_documents_per_industry_and_language(filed):
    _, filer = filed
    assert Counter(d["kind"] for d in filer.documents) == {"food": 9, "hotel": 9, "saas": 9, "realestate": 9}
    assert all(seed_console.is_seeded(d["key_id"]) for d in filer.documents if "key_id" in d)


def test_retail_files_nothing_yet(batch):
    for customer in batch:
        if customer.bot_id == "retail":
            assert not [row for conv in customer.conversations for row in conv.rows if row.kind == "tool"]


@pytest.mark.parametrize(
    "tool, field",
    [("food_place_order", "order_no"), ("hotel_create_booking", "booking_id"), ("saas_create_ticket", "ticket_id")],
)
def test_the_reply_names_the_number_that_was_filed(batch, tool, field):
    seen = 0
    for customer in batch:
        for conv in customer.conversations:
            for row in _tool_rows(conv, tool):
                number = json.loads(row.values["output"])[field]
                reply = next(r for r in conv.rows if r.kind == "message" and r.at > row.at)
                assert reply.values["role"] == "assistant"
                assert number in reply.values["content"], (number, reply.values["content"])
                seen += 1
    assert seen == 9


def test_a_viewing_is_saved_the_way_the_console_reads_it(batch):
    rows = [row for c in batch for conv in c.conversations for row in _tool_rows(conv, "book_property_viewing")]
    assert len(rows) == 9
    for row in rows:
        assert "IS ALREADY SAVED" in row.values["output"] and "#" in row.values["output"]


def test_a_document_is_dated_the_moment_its_tool_ran(filed):
    batch, filer = filed
    creating = {
        "food": "food_place_order",
        "hotel": "hotel_create_booking",
        "saas": "saas_create_ticket",
        "realestate": "book_property_viewing",
    }
    moments = {
        (customer.bot_id, row.at)
        for customer in batch
        for conv in customer.conversations
        for row in conv.rows
        if row.kind == "tool" and row.values["tool"] == creating.get(customer.bot_id)
    }
    assert {(d["kind"], d["at"]) for d in filer.documents} == moments


def test_a_food_order_is_priced_off_the_menu(filed):
    batch, filer = filed
    for document in filer.documents:
        if document["kind"] != "food":
            continue
        customer = next(c for c in batch if c.key_id == document["key_id"])
        placed = json.loads(_tool_rows(customer.conversations[-1], "food_place_order")[0].values["output"])
        assert placed["total"] == f"RM {food_models.subtotal_of(document['lines']) + document['fee']:.2f}"


def test_a_hotel_stay_is_one_the_live_tool_would_book(filed):
    from datetime import date

    from app.bots.registry import get_bot

    _, filer = filed
    stays = [d["stay"] for d in filer.documents if d["kind"] == "hotel"]
    for stay in stays:
        assert date.fromisoformat(stay["check_in"]) >= date.today()
        with local.serving(get_bot("hotel"), None):
            assert local._stay(stay["room_type"], stay["check_in"], stay["check_out"], stay["guests"]) == stay


@pytest.mark.parametrize("issue", seed_lines.ISSUES, ids=lambda issue: issue["query"])
def test_a_ticketed_issue_is_not_a_known_one(issue):
    """Or the bot on screen opens a ticket for something it had a fix for."""
    from app.bots.registry import get_bot

    output = seed_console._tool_output(get_bot("saas"), "saas_search_known_issues", {"query": issue["query"]})
    assert output == local.NO_KNOWN_ISSUE


def test_no_filer_means_no_documents():
    batch = seed_console.plan(NOW, random.Random(7))
    tools = {row.values["tool"] for c in batch for conv in c.conversations for row in conv.rows if row.kind == "tool"}
    assert tools <= {"hotel_search_rooms", "saas_search_known_issues"}


class RecordingStore:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return 0


def test_clearing_documents_touches_only_what_the_seed_filed():
    recording = RecordingStore()
    with patch.object(seed_documents, "store", recording):
        seed_documents.clear(seed_console.SEED_PREFIX)
    keyed = [(sql, params) for sql, params in recording.statements if "customer_key" in sql]
    assert [sql.split()[2] for sql, _ in keyed] == ["food_orders", "hotel_bookings", "saas_tickets"]
    assert all(params == ("ZZ.SEED%",) for _, params in keyed)
    assert [sql for sql, _ in recording.statements if "customer_key" not in sql] == [
        "DELETE v FROM realestate_viewings v JOIN seed_console_viewings s ON s.viewing_id = v.id",
        "DELETE FROM seed_console_viewings",
    ]
