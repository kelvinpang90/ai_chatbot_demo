"""The console seed (tasks 39.1, 39.2, 39.4): what it files, and what it must never touch.

The batch is built in memory and checked as data; the writing half is run
against a fake connection that records every statement. That the SQL itself
runs against MySQL 8 is the live run recorded under task 39.1 in tasks/todo.md.
"""
import json
import random
import time
from collections import Counter
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.bots.registry import get_bot
from app.config import settings
from app.console import cost
from app.routers import console
from app.services import crm_client, erp_client, phone
from app.services.api_client import ApiClientError
from app.services.user_store import UserProfile, identity, user_store
from app.tasks import cleanup, seed_console, seed_crm, seed_documents, seed_lines, seed_retail
from app.tools import crm as crm_tools
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


# --- retail over the ERP (task 39.3) --------------------------------------------


def _ago(days):
    return (date.fromtimestamp(NOW) - timedelta(days=days)).isoformat()


class FakeErp:
    """erp_os's routes the seed and the four read-only tools touch, and nothing else."""

    def __init__(self, *, down=False):
        self.down = down
        self.customers = [
            # Newest order yesterday, a contact, a phone: a buyer.
            {"id": 1, "code": "CUS-001", "name": "Sunrise Hypermart Sdn Bhd", "contact_person": "Lim Ah Kow", "phone": "+60 3-2284 1111", "currency": "MYR"},
            {"id": 2, "code": "CUS-002", "name": "Megamart Retail Group Sdn Bhd", "contact_person": "Tan Wei Ming", "phone": "+60 3-2142 2222", "currency": "MYR"},
            # The bot's own account: never a buyer.
            {"id": 3, "code": "WA-60123456789-2609051423", "name": "Ahmad Faizal", "contact_person": "Ahmad Faizal", "phone": "+60 12-345 6789", "currency": "MYR"},
            # No contact person to speak as.
            {"id": 4, "code": "CUS-004", "name": "Kedai Runcit Sdn Bhd", "contact_person": None, "phone": "+60 3-5555 4444", "currency": "MYR"},
            # Newest order older than the window.
            {"id": 5, "code": "CUS-005", "name": "Old Trading Sdn Bhd", "contact_person": "Wong Ah Beng", "phone": "+60 4-228 5555", "currency": "MYR"},
            # Ordered today: no "after" that is not also the quiet hour.
            {"id": 6, "code": "CUS-006", "name": "Today Mart Sdn Bhd", "contact_person": "Cheah Boon Hock", "phone": "+60 4-228 6666", "currency": "MYR"},
        ]
        self.orders = [
            {"document_no": "SO-SEED-00210", "customer_id": 6, "business_date": _ago(0), "status": "DRAFT", "currency": "MYR", "total_incl_tax": "100.0000"},
            {"document_no": "SO-SEED-00209", "customer_id": 1, "business_date": _ago(1), "status": "CONFIRMED", "currency": "MYR", "total_incl_tax": "2839.8400"},
            {"document_no": "SO-SEED-00208", "customer_id": 3, "business_date": _ago(2), "status": "CONFIRMED", "currency": "MYR", "total_incl_tax": "299.0000"},
            {"document_no": "SO-SEED-00207", "customer_id": 4, "business_date": _ago(3), "status": "INVOICED", "currency": "MYR", "total_incl_tax": "50.0000"},
            {"document_no": "SO-SEED-00206", "customer_id": 2, "business_date": _ago(5), "status": "FULLY_SHIPPED", "currency": "MYR", "total_incl_tax": "1200.5000"},
            {"document_no": "SO-SEED-00205", "customer_id": 1, "business_date": _ago(9), "status": "INVOICED", "currency": "MYR", "total_incl_tax": "980.0000"},
            {"document_no": "SO-SEED-00204", "customer_id": 1, "business_date": _ago(20), "status": "INVOICED", "currency": "MYR", "total_incl_tax": "430.1000"},
            {"document_no": "SO-SEED-00203", "customer_id": 1, "business_date": _ago(40), "status": "PAID", "currency": "MYR", "total_incl_tax": "77.0000"},
            {"document_no": "SO-SEED-00202", "customer_id": 5, "business_date": _ago(35), "status": "PAID", "currency": "MYR", "total_incl_tax": "10.0000"},
        ]
        self.gets = []

    def _up(self):
        if self.down:
            raise ApiClientError("erp api: failed: connection refused")

    def get(self, path, params=None):
        self._up()
        self.gets.append(path)
        if path == "/api/sales-orders":
            return {"items": self.orders[: params["page_size"]]}
        if path == "/api/customers":
            return {"items": self.customers if params["page"] == 1 else []}
        raise AssertionError(path)

    def find_customers(self, term, *, limit=5):
        self._up()
        return [row for row in self.customers if phone.matches(row["phone"], term)][:limit]

    def recent_orders(self, customer_id, *, limit=5):
        self._up()
        return [order for order in self.orders if order["customer_id"] == customer_id][:limit]

    def search_skus(self, keyword, *, limit=5):
        self._up()
        items = [
            {"id": 11, "code": "SKU-ELE-0001", "name": "Sony WF-C710N Wireless Earbuds", "unit_price_excl_tax": "299.0000", "unit_price_incl_tax": "328.9000", "currency": "MYR"},
            {"id": 12, "code": "SKU-ELE-0002", "name": "Khind Stand Fan 16 Inch SF16D", "unit_price_excl_tax": "129.0000", "unit_price_incl_tax": "139.3200", "currency": "MYR"},
        ]
        return erp_client.SkuMatches(items=items, total=5)

    def branch_inventory(self, sku_query, *, limit=5):
        self._up()
        return [
            {"sku_id": 11, "sku_code": "SKU-ELE-0001", "sku_name": "Sony WF-C710N Wireless Earbuds", "warehouses": [
                {"warehouse_id": 1, "warehouse_name": "KL", "available": "12.0000"},
                {"warehouse_id": 2, "warehouse_name": "Penang", "available": "0.0000"},
            ]},
            {"sku_id": 12, "sku_code": "SKU-ELE-0002", "sku_name": "Khind Stand Fan 16 Inch SF16D", "warehouses": [
                {"warehouse_id": 1, "warehouse_name": "KL", "available": "0.0000"},
            ]},
        ]


@pytest.fixture
def erp():
    fake = FakeErp()
    with patch.object(erp_client, "client", lambda: fake):
        yield fake


def test_buyers_are_the_accounts_with_a_recent_order_and_someone_to_speak_as(erp):
    found = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9)
    assert [a.company for a in found] == ["Sunrise Hypermart Sdn Bhd", "Megamart Retail Group Sdn Bhd"]
    assert found[0].latest == date.fromisoformat(_ago(1))
    assert found[0].contact == "Lim Ah Kow"
    assert seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=1) == found[:1]


def _retail_batch(erp, retail):
    return seed_console.plan(NOW, random.Random(7), FakeFiler(), retail)


def test_a_buyer_reads_out_the_orders_the_erp_holds(erp):
    retail = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9)
    batch = _retail_batch(erp, retail)
    buyers = [c for c in batch if c.name in {"Lim Ah Kow", "Tan Wei Ming"}]
    assert [c.bot_id for c in buyers] == ["retail", "retail"]

    lim = buyers[0]
    conversation = lim.conversations[-1]
    found = _tool_rows(conversation, "erp_find_customer")[0].values
    listed = _tool_rows(conversation, "erp_list_orders")[0].values
    assert json.loads(found["output"])[0]["customer_id"] == 1
    assert listed["input"] == {"customer_id": 1}
    orders = json.loads(listed["output"])
    assert [o["order_no"] for o in orders] == ["SO-SEED-00209", "SO-SEED-00205", "SO-SEED-00204", "SO-SEED-00203"]

    reply = next(r for r in conversation.rows if r.kind == "message" and r.at > _tool_rows(conversation, "erp_list_orders")[0].at)
    for order_no in ("SO-SEED-00209", "SO-SEED-00205", "SO-SEED-00204"):
        assert order_no in reply.values["content"]
    assert "RM 2,839.84" in reply.values["content"]
    assert "Sunrise Hypermart Sdn Bhd" in conversation.rows[1].values["content"]


def test_a_buyer_writes_after_their_newest_order(erp):
    retail = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9)
    for customer in _retail_batch(erp, retail):
        for account in retail:
            if customer.name == account.contact:
                moments = [row.at for conv in customer.conversations for row in conv.rows]
                assert moments == sorted(moments)
                assert date.fromtimestamp(customer.conversations[-1].rows[0].at) >= account.latest
                assert customer.conversations[-1].rows[-1].at < NOW - seed_console.QUIET_SECONDS + 15 * 60


def test_a_buyer_is_saved_without_the_number_they_were_looked_up_by(erp, mysql):
    retail = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9)
    batch = _retail_batch(erp, retail)
    buyers = [c for c in batch if c.name == "Lim Ah Kow"]
    seed_console.reseed(buyers, connect=lambda dsn: FakeConnection())
    assert user_store.get(buyers[0].key_id).phone is None


def test_the_other_retail_customers_ask_about_the_live_catalogue(erp):
    batch = _retail_batch(erp, seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9))
    retail = [c for c in batch if c.bot_id == "retail"]
    tools = Counter(row.values["tool"] for c in retail for conv in c.conversations for row in conv.rows if row.kind == "tool")
    assert tools["erp_find_customer"] == 2 and tools["erp_list_orders"] == 2
    assert tools["erp_search_sku"] + tools["erp_get_inventory"] == 16  # the other 16 of 18
    for customer in retail:
        for conv in customer.conversations:
            for row in conv.rows:
                if row.kind == "tool" and row.values["tool"] == "erp_get_inventory":
                    reply = next(r for r in conv.rows if r.kind == "message" and r.at > row.at)
                    assert "Sony WF-C710N Wireless Earbuds* 12" in reply.values["content"]
                    assert "KL 12" in reply.values["content"]


def test_a_product_the_catalogue_lost_falls_back_to_a_policy_question(erp):
    erp.search_skus = lambda keyword, limit=5: erp_client.SkuMatches(items=[], total=0)
    erp.branch_inventory = lambda sku_query, limit=5: []
    batch = _retail_batch(erp, [])
    tools = {row.values["tool"] for c in batch if c.bot_id == "retail" for conv in c.conversations for row in conv.rows if row.kind == "tool"}
    assert tools == set()


def test_an_erp_that_stops_answering_mid_seed_stops_the_seed(erp):
    retail = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9)
    erp.down = True
    with pytest.raises(RuntimeError, match="could not reach the ERP"):
        _retail_batch(erp, retail)


def test_an_unreachable_erp_clears_nothing(capsys):
    urls = {
        "mysql_url": "mysql://u:p@db:3306/chat",
        "redis_url": "redis://r:6379/0",
        "verticals_mysql_url": "mysql://u:p@db:3306/verticals",
    }
    down = FakeErp(down=True)
    with patch.multiple(settings, **urls), patch.object(erp_client, "client", lambda: down), patch.object(
        seed_documents, "clear"
    ) as clear_documents, patch.object(seed_console, "reseed") as reseed:
        assert seed_console.main([]) == 1
    clear_documents.assert_not_called()
    reseed.assert_not_called()
    assert "Seed failed" in capsys.readouterr().out


# --- the CRM pipeline (task 39.4) -----------------------------------------------


class FakeCrm:
    """crm_os's routes the seed writes through, and the one behaviour that shapes
    the code: `POST /api/contacts` makes a card of its own out of the initial
    fields, which is why the seed has to ask for the deals afterwards to find it.
    """

    def __init__(self):
        self.contacts = []
        self.deals = []
        self.activities = []
        self.down = False
        self.no_card = False
        self.n = 0

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}-{self.n}"

    def _up(self):
        if self.down:
            raise ApiClientError("crm api: failed: connection refused")

    def create_contact(self, *, name, phone, title, amount, notes):
        self._up()
        contact = {"id": self._id("contact"), "name": name, "phone": phone, "notes": notes}
        self.contacts.append(contact)
        if not self.no_card:
            self.deals.append(
                {
                    "id": self._id("deal"),
                    "contact_id": contact["id"],
                    "title": title,
                    "amount": amount,
                    "status": "lead",
                }
            )
        return contact

    def deals_for_contact(self, contact_id):
        self._up()
        return [deal for deal in self.deals if deal["contact_id"] == contact_id]

    def log_activity(self, *, deal_id, content, activity_type="WhatsApp"):
        self._up()
        self.activities.append({"deal_id": deal_id, "content": content})
        return {"id": self._id("activity")}

    def all_contacts(self):
        self._up()
        return list(self.contacts)

    def all_deals(self):
        self._up()
        return list(self.deals)

    def delete_contact(self, contact_id):
        self._up()
        self.contacts = [c for c in self.contacts if c["id"] != contact_id]
        # crm_os cascades to the cards; a seeded card only ever hangs off a seeded contact.
        self.deals = [d for d in self.deals if d["contact_id"] != contact_id]

    def delete_deal(self, deal_id):
        self._up()
        self.deals = [d for d in self.deals if d["id"] != deal_id]


@pytest.fixture
def crm():
    return FakeCrm()


def _crm_batch(erp, crm, retail=None):
    accounts = seed_retail.accounts(erp, now=NOW, days=seed_console.DAYS, wanted=9) if retail is None else retail
    return seed_console.plan(NOW, random.Random(7), FakeFiler(), accounts, seed_crm.Leads(crm))


def _lead_rows(batch):
    return [
        (customer, conversation, row)
        for customer in batch
        for conversation in customer.conversations
        for row in conversation.rows
        if row.kind == "tool" and row.values["tool"] == "crm_create_lead"
    ]


def test_every_viewing_and_two_retail_customers_a_language_leave_an_enquiry(erp, crm):
    batch = _crm_batch(erp, crm)
    assert Counter(c.bot_id for c, _, _ in _lead_rows(batch)) == {"realestate": 9, "retail": 6}
    assert len(crm.contacts) == 15 and len(crm.deals) == 15 and len(crm.activities) == 15


def test_a_retail_enquiry_is_priced_off_the_catalogue(erp, crm):
    batch = _crm_batch(erp, crm)
    _, conversation, lead = next(row for row in _lead_rows(batch) if row[0].bot_id == "retail")
    searched = _tool_rows(conversation, "erp_search_sku")[0]
    sku = json.loads(searched.values["output"])["products"][0]
    given = lead.values["input"]
    # Every language writes the quantity first: "2 台 X", "2 x X", "2 unit X".
    quantity = int(given["requirement"].split()[0])
    assert 2 <= quantity <= 6
    assert sku["name"] in given["requirement"]
    assert given["amount"] == round(float(sku["unit_price_incl_tax"]) * quantity, 2)
    # The enquiry follows the search it was priced off, in the same conversation.
    assert lead.at > searched.at
    assert given["delivery_address"] in seed_lines.ADDRESSES


def test_a_viewing_records_the_enquiry_in_the_same_turn(erp, crm):
    batch = _crm_batch(erp, crm)
    _, conversation, lead = next(row for row in _lead_rows(batch) if row[0].bot_id == "realestate")
    booked = _tool_rows(conversation, "book_property_viewing")[0]
    assert booked.at < lead.at
    # One reply covers both calls, the way realestate's persona has it.
    after = [row for row in conversation.rows if row.kind == "message" and row.at > lead.at]
    assert after[0].values["role"] == "assistant"
    listing = next(
        row
        for row in get_bot("realestate").context_data["listings"]
        if row["listing_id"] == booked.values["input"]["listing_id"]
    )
    assert lead.values["input"]["amount"] == float(listing["price_rm"])
    assert listing["listing_id"] in lead.values["input"]["requirement"]


def test_the_number_a_seeded_customer_gives_is_one_the_live_tool_would_accept(erp, crm):
    batch = _crm_batch(erp, crm)
    numbers = {}
    for customer, conversation, lead in _lead_rows(batch):
        number = lead.values["input"]["phone"]
        assert number == seed_crm.phone_for(customer.key_id)
        # What `crm_create_lead` puts a lead through before writing it: a number
        # it would refuse is a card the live system could not have made.
        assert crm_tools._usable(customer.name, number, "2 fans", 100.0) is not None
        # The customer read it out, which is the only way a lead gets a number
        # from somebody whose handset the channel is not telling us about.
        assert any(number in row.values["content"] for row in conversation.rows if row.kind == "message")
        numbers[customer.key_id] = number
    assert len(set(numbers.values())) == len(numbers)
    # Nobody real is on this block, so a lookup by a customer's own number misses it.
    assert not any(phone.matches(number, "+60 17-394 8123") for number in numbers.values())


def test_the_card_the_console_shows_is_the_one_crm_os_made(erp, crm):
    batch = _crm_batch(erp, crm)
    _, _, lead = _lead_rows(batch)[0]
    card = json.loads(lead.values["output"])
    deal = next(d for d in crm.deals if d["id"] == card["deal_id"])
    contact = next(c for c in crm.contacts if c["id"] == card["contact_id"])
    assert card["title"] == deal["title"] and card["amount"] == deal["amount"]
    assert card["status"] == "lead" and card["activity_logged"] is True
    assert card["contact_name"] == contact["name"]


def test_the_note_inside_the_card_is_the_one_the_live_tool_writes(erp, crm):
    batch = _crm_batch(erp, crm)
    _, _, lead = next(row for row in _lead_rows(batch) if row[0].bot_id == "retail")
    card = json.loads(lead.values["output"])
    note = next(a for a in crm.activities if a["deal_id"] == card["deal_id"])["content"]
    given = lead.values["input"]
    assert note == crm_tools._activity_note(
        crm_tools._Lead(
            name=given["name"],
            phone=given["phone"],
            title=card["title"],
            requirement=given["requirement"],
            amount=given["amount"],
            delivery_address=given["delivery_address"],
        )
    )
    assert given["delivery_address"] in note


def test_every_seeded_row_carries_the_seed_mark_and_nothing_else_does(erp, crm):
    _crm_batch(erp, crm)
    assert all(contact["notes"] == seed_crm.NOTES for contact in crm.contacts)
    assert all(crm_client.is_marked(deal["title"], crm_client.SEED_MARK) for deal in crm.deals)
    # Neither mark is a prefix of the other, so neither deletion rule can reach
    # the other's rows. This is the whole of what keeps the two jobs apart.
    assert not any(crm_client.is_marked(deal["title"]) for deal in crm.deals)
    assert not crm_client.is_marked(crm_client.SEED_MARK + " anything")
    assert not crm_client.is_marked(crm_client.DEMO_MARK + " anything", crm_client.SEED_MARK)


def _two_kinds(crm):
    """One row a live demo left behind, one the seed left behind."""
    crm.create_contact(
        name="Walk-in",
        phone="+60 12-345 6789",
        title=crm_client.marked("10 fans"),
        amount=100.0,
        notes=crm_tools.NEW_CONTACT_NOTES,
    )
    seed_crm.Leads(crm).lead(
        name="Seeded", phone=seed_crm.phone_for("ZZ.SEED0007"), requirement="2 fans", amount=50.0
    )


def test_the_seed_clears_its_own_rows_and_leaves_a_live_demos_where_they_are(crm):
    _two_kinds(crm)
    assert seed_crm.clear(crm) == 1  # the contact; crm_os cascades to its card
    assert [c["name"] for c in crm.contacts] == ["Walk-in"]
    assert [d["title"] for d in crm.deals] == ["[DEMO] 10 fans"]


def test_the_cleanup_between_demos_leaves_the_seeded_rows_where_they_are(crm):
    """The trap this task was written around: `cleanup` deletes every `[DEMO]`
    row between demos, and last night's conversations name the seeded cards."""
    _two_kinds(crm)
    report = cleanup.Report()
    cleanup._clear_crm_cards(crm, report)
    cleanup._clear_crm_contacts(crm, report)
    assert [c["name"] for c in crm.contacts] == ["Seeded"]
    assert [d["title"] for d in crm.deals] == ["[DEMO-SEED] 2 fans"]


def test_no_crm_board_means_no_enquiries(erp):
    assert _lead_rows(seed_console.plan(NOW, random.Random(7), FakeFiler(), [])) == []


def test_a_crm_that_stops_answering_stops_the_seed(erp, crm):
    crm.down = True
    with pytest.raises(ApiClientError):
        _crm_batch(erp, crm)


def test_a_contact_crm_os_filed_no_card_for_stops_the_seed(erp, crm):
    crm.no_card = True
    with pytest.raises(RuntimeError, match="no card"):
        _crm_batch(erp, crm)


@pytest.mark.parametrize("missing", ["crm_base_url", "crm_email", "crm_password"])
def test_refuses_to_run_without_the_crm(missing, capsys):
    given = {
        "mysql_url": "mysql://u:p@db:3306/chat",
        "redis_url": "redis://r:6379/0",
        "verticals_mysql_url": "mysql://u:p@db:3306/verticals",
        "crm_base_url": "https://crm.example.com",
        "crm_email": "demo@example.com",
        "crm_password": "secret",
    }
    given[missing] = ""
    with patch.multiple(settings, **given):
        assert seed_console.main([]) == 2
    assert "CRM_BASE_URL" in capsys.readouterr().out


def test_an_unreachable_erp_clears_no_crm_rows(crm):
    """The ERP is read first so that a night it is down changes nothing at all --
    the pipeline included, because its rows are named by last night's conversations.
    """
    urls = {
        "mysql_url": "mysql://u:p@db:3306/chat",
        "redis_url": "redis://r:6379/0",
        "verticals_mysql_url": "mysql://u:p@db:3306/verticals",
    }
    _two_kinds(crm)
    down = FakeErp(down=True)
    with patch.multiple(settings, **urls), patch.object(erp_client, "client", lambda: down), patch.object(
        crm_client, "client", lambda: crm
    ), patch.object(seed_documents, "clear"), patch.object(seed_console, "reseed"):
        assert seed_console.main([]) == 1
    assert len(crm.contacts) == 2
