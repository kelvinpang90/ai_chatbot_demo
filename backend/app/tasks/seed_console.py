"""Give the director's console something to show before anybody has written.

Run nightly on the VPS, half an hour after erp_os resets its own demo data:

    docker exec ai_chatbot_backend python -m app.tasks.seed_console
    docker exec ai_chatbot_backend python -m app.tasks.seed_console --clear

Each run clears the previous batch and files a fresh one, dated across the four
weeks before the moment it runs, so the console never opens on a list whose
newest customer wrote a month ago. `--clear` stops after the first half.

Some of those conversations end in a food order, a booking, a ticket or a
viewing, and those are filed in the back office too (`seed_documents.py`), so a
number the console shows is a row `/admin` shows.

What is seeded is decided in tasks/todo.md, batch 07, and so is what is not: the
live feed, a takeover, the tools switch and the failure drill are all left alone.
Each of those is one flag for the whole backend, and a seeded value that is not
the default is a real demo broken on purpose.

Every seeded customer is filed under a BSUID-shaped key -- `ZZ.SEED0001` -- and
that prefix is the whole of the rule for what a run may delete:

  * BSUID-shaped because the console looks a name up through `identity()`,
    which takes a phone number or a BSUID and nothing else.
  * `ZZ` because ISO 3166 reserves it for private use, so no real customer's
    user id starts with it.
  * No phone number, so nothing the console can send -- the demo summary, a
    person's reply -- can reach anybody's handset.

Unlike the audit log this writes into, a failure here is loud. `AuditStore`
drops a row rather than let a customer's reply wait on MySQL; a seed that
dropped rows would report a success and leave the console half-filled, which is
exactly the screen this exists to prevent. So this opens its own connection,
clears and refills in one transaction -- the console reads either last night's
batch or tonight's, never half of each -- and exits non-zero on anything.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import string
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.bots.registry import get_bot
from app.config import settings
from app.console import cost
from app.routers.whatsapp_webhook import GREETING_SUFFIX_EN
from app.services import audit
from app.services.clock import sql_timestamp
from app.services.mysql_url import connect as _default_connect
from app.services.mysql_url import dsn as _mysql_dsn
from app.services.user_store import UserProfile, UserStore, user_store
from app.tasks import seed_documents, seed_lines
from app.tools import food as food_tools
from app.tools import local
from app.tools import realestate as realestate_tools
from app.tools.registry import CATALOGUE
from app.verticals.food import models as food_models

logger = logging.getLogger(__name__)

SEED_PREFIX = "ZZ.SEED"
BOTS = ("retail", "food", "realestate", "hotel", "saas")
DAYS = 28
ORDINARY_PER_COMBINATION = 6
# Of those six, how many end their latest conversation in a document (task 39.2).
DEALS_PER_COMBINATION = 3
# Share of customers who also wrote once before, days earlier. A list in which
# every customer has exactly one conversation reads as a list somebody generated.
RETURNING_SHARE = 0.3
# When people write to a shop, in the container's local time (Asia/Kuala_Lumpur).
FIRST_HOUR, LAST_HOUR = 9, 22
# Nothing seeded lands in the last hour, so the first real conversation of the
# day is always the newest one and the console follows it.
QUIET_SECONDS = 60 * 60
# A Redis scan wide enough to find every seeded profile among the real ones.
PROFILE_SCAN_LIMIT = 5000
# Roughly what the system prompt plus the bot's catalogue weighs, in tokens.
SYSTEM_TOKENS = (2600, 4200)


@dataclass
class Row:
    """One line in one of the three audit tables, in the order it happened."""

    kind: str  # "message", "tool" or "usage"
    at: float
    values: dict


@dataclass
class Conversation:
    conversation_id: str
    bot_id: str
    rows: list[Row] = field(default_factory=list)


@dataclass
class Customer:
    key_id: str
    name: str
    language: str
    bot_id: str
    # Oldest first.
    conversations: list[Conversation] = field(default_factory=list)


def seed_key(n: int) -> str:
    return f"{SEED_PREFIX}{n:04d}"


def is_seeded(key_id: str | None) -> bool:
    return str(key_id or "").startswith(SEED_PREFIX)


# --- what to write ------------------------------------------------------------


@dataclass
class Step:
    """One tool call inside a turn. `run` is handed the moment it was made."""

    tool: str
    input: dict
    run: Callable[[float], str]


@dataclass
class Exchange:
    """A customer's line, the tools it set off, and the reply given what they returned."""

    ask: str
    steps: list[Step]
    reply: Callable[[list[str]], str]


def plan(now: float, rng: random.Random, filer: seed_documents.Filer | None = None) -> list[Customer]:
    """The whole batch. Files documents through `filer` as it goes, if given one."""
    customers = []
    for bot_index, bot_id in enumerate(BOTS):
        bot = get_bot(bot_id)
        for language in seed_lines.LANGUAGES:
            for i in range(ORDINARY_PER_COMBINATION):
                name = seed_lines.NAMES[language][bot_index * ORDINARY_PER_COMBINATION + i]
                customer = Customer(
                    key_id=seed_key(len(customers) + 1),
                    name=name,
                    language=language,
                    bot_id=bot_id,
                )
                latest = _moment(now, rng, days_ago=rng.randrange(DAYS))
                if rng.random() < RETURNING_SHARE:
                    earlier = latest - rng.randint(2, 9) * 86400
                    if earlier > now - DAYS * 86400:
                        exchanges = _ordinary(bot, customer, rng, topics=1)
                        customer.conversations.append(_conversation(customer, earlier, rng, exchanges))
                deal = _DEALS.get(bot_id)
                if filer is not None and deal is not None and i < DEALS_PER_COMBINATION:
                    exchanges = deal(bot, customer, rng, filer, latest)
                else:
                    exchanges = _ordinary(bot, customer, rng, topics=rng.choice((1, 2)))
                customer.conversations.append(_conversation(customer, latest, rng, exchanges))
                customers.append(customer)
    return customers


def _moment(now: float, rng: random.Random, *, days_ago: int) -> float:
    """A time in opening hours that many days back, never in the quiet hour."""
    day = datetime.fromtimestamp(now) - timedelta(days=days_ago)
    at = day.replace(
        hour=rng.randint(FIRST_HOUR, LAST_HOUR - 1),
        minute=rng.randrange(60),
        second=rng.randrange(60),
        microsecond=0,
    ).timestamp()
    # Today's draw can land later than now; yesterday at the same hour cannot.
    return at if at < now - QUIET_SECONDS else at - 86400


def _conversation(customer: Customer, start: float, rng: random.Random, exchanges: list[Exchange]) -> Conversation:
    bot = get_bot(customer.bot_id)
    model = bot.model or settings.anthropic_model
    conversation = Conversation(conversation_id=audit.new_conversation_id(), bot_id=customer.bot_id)
    rows = conversation.rows
    system = rng.randint(*SYSTEM_TOKENS)
    cached = False

    def usage(at: float, input_tokens: int, output_tokens: int) -> None:
        nonlocal cached
        tokens = {
            "input": input_tokens,
            "output": output_tokens,
            "cache_write": 0 if cached else system,
            "cache_read": system if cached else 0,
        }
        cached = True
        rows.append(
            Row(
                "usage",
                at,
                {
                    "model": model,
                    "input_tokens": tokens["input"],
                    "output_tokens": tokens["output"],
                    "cache_write_tokens": tokens["cache_write"],
                    "cache_read_tokens": tokens["cache_read"],
                    "cost_myr": cost.cost_myr(model, tokens),
                },
            )
        )

    at = start
    rows.append(Row("message", at, {"role": "assistant", "content": f"{bot.disclaimer.en}\n\n{GREETING_SUFFIX_EN}"}))
    closing = _from_topic(bot, rng.choice(seed_lines.THANKS[customer.language]))
    history = 0
    for exchange in [*exchanges, closing]:
        at += rng.uniform(15, 120)
        rows.append(Row("message", at, {"role": "user", "content": exchange.ask}))
        history += len(exchange.ask) // 2 + 20
        outputs = []
        for step in exchange.steps:
            usage(at + rng.uniform(1.0, 2.5), history + rng.randint(20, 80), rng.randint(40, 90))
            at += rng.uniform(2.5, 4.0)
            output = step.run(at)
            outputs.append(output)
            rows.append(
                Row(
                    "tool",
                    at,
                    {
                        "tool": step.tool,
                        "tool_use_id": "toolu_" + "".join(rng.choices(string.ascii_letters + string.digits, k=24)),
                        "input": step.input,
                        "output": output,
                        "duration_ms": rng.randint(8, 60),
                        "status": "ok",
                    },
                )
            )
            history += len(output) // 4
        reply = exchange.reply(outputs)
        reply_tokens = len(reply) // 2 + rng.randint(10, 40)
        at += rng.uniform(2.0, 6.0)
        usage(at - 0.3, history + rng.randint(20, 80), reply_tokens)
        rows.append(Row("message", at, {"role": "assistant", "content": reply}))
        history += reply_tokens
    return conversation


def _tool_output(bot, name: str, tool_input: dict) -> str:
    """What the real tool answers today, so the card is the one it would draw."""
    with local.serving(bot, None):
        return str(CATALOGUE[name].call(tool_input))


def _ordinary(bot, customer: Customer, rng: random.Random, *, topics: int) -> list[Exchange]:
    chosen = rng.sample(seed_lines.TOPICS[customer.bot_id][customer.language], topics)
    return [_from_topic(bot, topic) for topic in chosen]


def _from_topic(bot, topic: seed_lines.Topic) -> Exchange:
    steps = []
    if topic.tool:
        steps.append(Step(topic.tool, topic.tool_input, lambda at: _tool_output(bot, topic.tool, topic.tool_input)))
    return Exchange(topic.ask, steps, lambda outputs: topic.reply)


def _day_text(day: date, language: str) -> str:
    if language == "zh":
        return f"{day.month}月{day.day}日"
    if language == "ms":
        return f"{day.day}/{day.month}"
    return f"{day.day} {day.strftime('%b')}"


# --- conversations that end in a document (task 39.2) --------------------------
#
# Each files its document through the model function the live tool calls, and
# hands the console the output the live tool would have: the same helpers build
# it where they can be reached (`for_the_guest`, `_confirmation`), and the food
# order's reply is rebuilt field for field where they cannot, because the tool
# itself would stamp the order with the clock rather than the moment it happened.


def _food_deal(bot, customer: Customer, rng: random.Random, filer: seed_documents.Filer, start: float) -> list[Exchange]:
    text = seed_lines.DEALS["food"][customer.language]
    menu = food_tools._menu()
    picks = rng.sample(sorted(menu), rng.randint(1, 3))
    cart = {item_id: rng.randint(1, 3) for item_id in picks}
    items = [{"item_id": item_id, "quantity": quantity} for item_id, quantity in cart.items()]
    address = rng.choice(seed_lines.ADDRESSES)

    def cart_reply(outputs: list[str]) -> str:
        shown = json.loads(outputs[0])
        lines = "\n".join(text["cart_line"].format(**line) for line in shown["cart"])
        return text["cart_reply"].format(lines=lines, fee=shown["delivery_fee"], total=shown["total"])

    def place(at: float) -> str:
        lines = food_tools._priced(cart, menu)
        fee = food_tools._fee()
        order_no = food_models.order_no(
            filer.food_order(key_id=customer.key_id, name=customer.name, lines=lines, address=address, fee=fee, at=at)
        )
        total = food_tools._rm(food_models.subtotal_of(lines) + fee)
        return json.dumps(
            {
                "order_no": order_no,
                "status": food_models.RECEIVED,
                "items": [f"{line.quantity} x {line.name}" for line in lines],
                "total": total,
                "delivery_address": address,
                "note": (
                    f"The order IS PLACED as {order_no}, total {total}. Confirm it to the "
                    "customer in one short message with the order number and the total. "
                    f"It should arrive in about {_food_minutes()} minutes, and they will get "
                    "a message by themselves when it leaves the kitchen."
                ),
            },
            ensure_ascii=False,
        )

    def placed_reply(outputs: list[str]) -> str:
        placed = json.loads(outputs[0])
        return text["placed_reply"].format(order_no=placed["order_no"], total=placed["total"], minutes=_food_minutes())

    asked = text["joiner"].join(text["item"].format(quantity=q, name=menu[i]["name"]) for i, q in cart.items())
    return [
        Exchange(
            text["ask_items"].format(items=asked),
            [Step("food_update_cart", {"items": items}, lambda at: _tool_output(bot, "food_update_cart", {"items": items}))],
            cart_reply,
        ),
        Exchange(
            text["ask_address"].format(address=address),
            [Step("food_place_order", {"delivery_address": address, "customer_name": customer.name}, place)],
            placed_reply,
        ),
    ]


def _food_minutes() -> int:
    return round((settings.push_delay_seconds + food_models.RIDER_MINUTES * 60) / 60)


def _hotel_deal(bot, customer: Customer, rng: random.Random, filer: seed_documents.Filer, start: float) -> list[Exchange]:
    text = seed_lines.DEALS["hotel"][customer.language]
    location = rng.choice(("Langkawi", "Penang"))
    guests = rng.choice((2, 2, 2, 3, 4))
    nights = rng.randint(1, 4)
    # Booked for a stay still ahead of whoever opens the back office: the live
    # tool refuses a check-in that has passed, and so does `_stay` below.
    check_in = max(
        date.fromtimestamp(start) + timedelta(days=rng.randint(7, 45)),
        date.today() + timedelta(days=rng.randint(1, 14)),
    )
    check_out = check_in + timedelta(days=nights)
    search_input = {"location": location, "guests": guests}
    found = _tool_output(bot, "hotel_search_rooms", search_input)
    rooms = json.loads(found)
    room = rng.choice(rooms)
    place = seed_lines.LOCATION_WORDS[customer.language][location]
    booking_input = {
        "room_type": room["room_type"],
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "guests": guests,
    }

    def book(at: float) -> str:
        with local.serving(bot, None):
            stay = local._stay(room["room_type"], booking_input["check_in"], booking_input["check_out"], guests)
        booking = filer.hotel_booking(key_id=customer.key_id, name=customer.name, stay=stay, at=at)
        return local._dump(booking.for_the_guest())

    def booked_reply(outputs: list[str]) -> str:
        booked = json.loads(outputs[0])
        return text["booked_reply"].format(
            booking_id=booked["booking_id"],
            room_type=booked["room_type"],
            check_in=_day_text(date.fromisoformat(booked["check_in"]), customer.language),
            check_out=_day_text(date.fromisoformat(booked["check_out"]), customer.language),
            nights=booked["nights"],
            guests=booked["guests"],
            total=f"{booked['total_rm']:,.2f}",
        )

    rooms_lines = "\n".join(
        text["room_line"].format(room_type=r["room_type"], price=round(r["price_per_night_rm"])) for r in rooms
    )
    return [
        Exchange(
            text["ask_rooms"].format(
                location=place, guests=guests, nights=nights, check_in=_day_text(check_in, customer.language)
            ),
            [Step("hotel_search_rooms", search_input, lambda at: found)],
            lambda outputs: text["rooms_reply"].format(location=place, guests=guests, lines=rooms_lines),
        ),
        Exchange(
            text["ask_book"].format(room_type=room["room_type"]),
            [Step("hotel_create_booking", booking_input, book)],
            booked_reply,
        ),
    ]


def _saas_deal(bot, customer: Customer, rng: random.Random, filer: seed_documents.Filer, start: float) -> list[Exchange]:
    text = seed_lines.DEALS["saas"][customer.language]
    issue = rng.choice(seed_lines.ISSUES)
    search_input = {"query": issue["query"]}
    ticket_input = {"subject": issue["subject"], "description": issue["description"], "priority": issue["priority"]}

    def open_ticket(at: float) -> str:
        ticket = filer.ticket(key_id=customer.key_id, name=customer.name, at=at, **ticket_input)
        return local._dump(ticket.for_the_customer())

    def ticket_reply(outputs: list[str]) -> str:
        opened = json.loads(outputs[1])
        words = seed_lines.PRIORITY_WORDS[customer.language]
        return text["ticket_reply"].format(ticket_id=opened["ticket_id"], priority=words[opened["priority"]])

    return [
        Exchange(
            issue["ask"][customer.language],
            [
                Step("saas_search_known_issues", search_input, lambda at: _tool_output(bot, "saas_search_known_issues", search_input)),
                Step("saas_create_ticket", ticket_input, open_ticket),
            ],
            ticket_reply,
        ),
    ]


def _realestate_deal(bot, customer: Customer, rng: random.Random, filer: seed_documents.Filer, start: float) -> list[Exchange]:
    text = seed_lines.DEALS["realestate"][customer.language]
    listing = rng.choice([row for row in bot.context_data["listings"] if row.get("status") == "Available"])
    viewing_day = date.fromtimestamp(start) + timedelta(days=rng.randint(2, 10))
    preferred_time = rng.choice(seed_lines.VIEWING_TIMES[customer.language])
    viewing_input = {
        "customer_name": customer.name,
        "listing_id": listing["listing_id"],
        "viewing_date": viewing_day.isoformat(),
        "preferred_time": preferred_time,
    }
    words = {
        "listing_id": listing["listing_id"],
        "area": listing["area"],
        "viewing_date": _day_text(viewing_day, customer.language),
        "preferred_time": preferred_time,
        "name": customer.name,
    }

    def book(at: float) -> str:
        viewing = filer.viewing(
            name=customer.name,
            listing_id=listing["listing_id"],
            viewing_date=viewing_day,
            preferred_time=preferred_time,
            at=at,
        )
        return realestate_tools._confirmation(viewing, how="gave these details in the chat")

    return [
        Exchange(
            text["ask_viewing"].format(**words),
            [Step("book_property_viewing", viewing_input, book)],
            lambda outputs: text["viewing_reply"].format(**words),
        ),
    ]


_DEALS = {
    "food": _food_deal,
    "hotel": _hotel_deal,
    "saas": _saas_deal,
    "realestate": _realestate_deal,
}


# --- writing it ---------------------------------------------------------------


@dataclass
class Counts:
    customers: int = 0
    messages: int = 0
    tool_calls: int = 0
    usage: int = 0
    cleared_rows: int = 0
    cleared_profiles: int = 0


_TABLES = ("chat_messages", "tool_calls", "model_usage")


def reseed(customers: list[Customer], *, connect=_default_connect, users: UserStore = user_store) -> Counts:
    """Replace last night's batch with this one. Raises on any failure."""
    counts = Counts()
    conn = _open(connect)
    try:
        conn.begin()
        with conn.cursor() as cursor:
            counts.cleared_rows = _delete_rows(cursor)
            for customer in customers:
                _insert_customer(cursor, customer, counts)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    counts.cleared_profiles = _delete_profiles(users)
    for customer in customers:
        users.save(_profile(customer))
    counts.customers = len(customers)
    return counts


def clear(*, connect=_default_connect, users: UserStore = user_store) -> Counts:
    """Take the seeded batch away and file nothing in its place."""
    return reseed([], connect=connect, users=users)


def _open(connect):
    conn_dsn = _mysql_dsn(settings.mysql_url, feature="the console seed")
    if conn_dsn is None:
        raise RuntimeError("MYSQL_URL is not a usable mysql:// url, so there is no audit log to seed")
    conn = connect(conn_dsn)
    with conn.cursor() as cursor:
        # The tables create themselves on the first real message; a fresh
        # database that has not had one yet is still somewhere to seed.
        for statement in audit.SCHEMA:
            cursor.execute(statement)
    return conn


def _delete_rows(cursor) -> int:
    deleted = 0
    for table in _TABLES:
        deleted += cursor.execute(f"DELETE FROM {table} WHERE key_id LIKE %s", (f"{SEED_PREFIX}%",))
    return deleted


def _insert_customer(cursor, customer: Customer, counts: Counts) -> None:
    for conversation in customer.conversations:
        head = (conversation.conversation_id, customer.key_id)
        message_id = None
        for row in conversation.rows:
            v = row.values
            if row.kind == "message":
                cursor.execute(
                    "INSERT INTO chat_messages"
                    " (conversation_id, key_id, channel, bot_id, role, content, source, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (*head, audit.WHATSAPP, conversation.bot_id, v["role"], v["content"], audit.TEXT, sql_timestamp(row.at)),
                )
                counts.messages += 1
                if v["role"] == "user":
                    # What a tool call and a usage line hang off, as in a live turn.
                    message_id = cursor.lastrowid
            elif row.kind == "tool":
                cursor.execute(
                    "INSERT INTO tool_calls"
                    " (conversation_id, key_id, message_id, tool, tool_use_id, input, output,"
                    "  duration_ms, status, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        *head,
                        message_id,
                        v["tool"],
                        v["tool_use_id"],
                        json.dumps(v["input"], ensure_ascii=False),
                        v["output"],
                        v["duration_ms"],
                        v["status"],
                        sql_timestamp(row.at),
                    ),
                )
                counts.tool_calls += 1
            else:
                cursor.execute(
                    "INSERT INTO model_usage"
                    " (conversation_id, key_id, message_id, bot_id, model, input_tokens,"
                    "  output_tokens, cache_write_tokens, cache_read_tokens, cost_myr, created_at)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        *head,
                        message_id,
                        conversation.bot_id,
                        v["model"],
                        v["input_tokens"],
                        v["output_tokens"],
                        v["cache_write_tokens"],
                        v["cache_read_tokens"],
                        v["cost_myr"],
                        sql_timestamp(row.at),
                    ),
                )
                counts.usage += 1


def _delete_profiles(users: UserStore) -> int:
    seeded = [p.key_id for p in users.everyone(limit=PROFILE_SCAN_LIMIT) if is_seeded(p.key_id)]
    for key_id in seeded:
        users.delete(key_id)
    return len(seeded)


def _profile(customer: Customer) -> UserProfile:
    latest = customer.conversations[-1]
    return UserProfile(
        key_id=customer.key_id,
        user_id=customer.key_id,
        bot_id=customer.bot_id,
        conversation_id=latest.conversation_id,
        display_name=customer.name,
        language=customer.language,
        first_seen=customer.conversations[0].rows[0].at,
    )


def _profiles_landed(customers: list[Customer]) -> bool:
    """Is the batch in Redis, rather than in this process's fallback memory?

    `UserStore` keeps a record in memory when Redis will not take it, which is
    right for a customer mid-conversation and wrong here: the process exits a
    second later and the names go with it. A store of its own has no such
    memory, so what it reads back came from Redis.
    """
    return not customers or UserStore(settings.redis_url).get(customers[-1].key_id) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clear", action="store_true", help="remove the seeded batch and seed nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not settings.mysql_url or not settings.redis_url or not settings.verticals_mysql_url:
        print(
            "MYSQL_URL, REDIS_URL and VERTICALS_MYSQL_URL must all be set: the console reads"
            " names from Redis, and the documents a conversation mentions live in the verticals database."
        )
        return 2

    filer = seed_documents.Filer()
    try:
        # Documents first, conversations second: a conversation names the number
        # its document was given. A failure between the two leaves documents with
        # no conversation, which the next run clears before filing again.
        seed_documents.clear(SEED_PREFIX)
        customers = [] if args.clear else plan(time.time(), random.Random(), filer)
        counts = reseed(customers)
    except Exception as failure:
        # The audit half is one transaction and rolls back whole; a failure after
        # its commit (Redis) leaves tonight's rows in place with stale names.
        print(f"Seed failed: {failure}")
        return 1
    if not _profiles_landed(customers):
        print("Rows were written but the names did not reach Redis; the console will show keys, not names.")
        return 1

    print(f"Cleared:   {counts.cleared_rows} rows, {counts.cleared_profiles} profiles")
    print(
        f"Seeded:    {counts.customers} customers, {counts.messages} messages,"
        f" {counts.tool_calls} tool calls, {counts.usage} model calls, {filer.filed} documents"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
