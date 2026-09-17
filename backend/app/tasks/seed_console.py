"""Give the director's console something to show before anybody has written.

Run nightly on the VPS, half an hour after erp_os resets its own demo data:

    docker exec ai_chatbot_backend python -m app.tasks.seed_console
    docker exec ai_chatbot_backend python -m app.tasks.seed_console --clear

Each run clears the previous batch and files a fresh one, dated across the four
weeks before the moment it runs, so the console never opens on a list whose
newest customer wrote a month ago. `--clear` stops after the first half.

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.bots.registry import get_bot
from app.config import settings
from app.console import cost
from app.routers.whatsapp_webhook import GREETING_SUFFIX_EN
from app.services import audit
from app.services.clock import sql_timestamp
from app.services.mysql_url import connect as _default_connect
from app.services.mysql_url import dsn as _mysql_dsn
from app.services.user_store import UserProfile, UserStore, user_store
from app.tasks import seed_lines
from app.tools import local
from app.tools.registry import CATALOGUE

logger = logging.getLogger(__name__)

SEED_PREFIX = "ZZ.SEED"
BOTS = ("retail", "food", "realestate", "hotel", "saas")
DAYS = 28
ORDINARY_PER_COMBINATION = 6
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


def plan(now: float, rng: random.Random) -> list[Customer]:
    """The whole batch, built in memory. Touches no database."""
    customers = []
    for bot_index, bot_id in enumerate(BOTS):
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
                        customer.conversations.append(_conversation(customer, earlier, rng, topics=1))
                customer.conversations.append(_conversation(customer, latest, rng, topics=rng.choice((1, 2))))
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


def _conversation(customer: Customer, start: float, rng: random.Random, *, topics: int) -> Conversation:
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
    chosen = rng.sample(seed_lines.TOPICS[customer.bot_id][customer.language], topics)
    closing = rng.choice(seed_lines.THANKS[customer.language])
    history = 0
    for topic in [*chosen, closing]:
        at += rng.uniform(15, 120)
        rows.append(Row("message", at, {"role": "user", "content": topic.ask}))
        history += len(topic.ask) // 2 + 20
        if topic.tool:
            output = _tool_output(bot, topic.tool, topic.tool_input)
            usage(at + rng.uniform(1.0, 2.5), history + rng.randint(20, 80), rng.randint(40, 90))
            at += rng.uniform(2.5, 4.0)
            rows.append(
                Row(
                    "tool",
                    at,
                    {
                        "tool": topic.tool,
                        "tool_use_id": "toolu_" + "".join(rng.choices(string.ascii_letters + string.digits, k=24)),
                        "input": topic.tool_input,
                        "output": output,
                        "duration_ms": rng.randint(8, 60),
                        "status": "ok",
                    },
                )
            )
            history += len(output) // 4
        reply_tokens = len(topic.reply) // 2 + rng.randint(10, 40)
        at += rng.uniform(2.0, 6.0)
        usage(at - 0.3, history + rng.randint(20, 80), reply_tokens)
        rows.append(Row("message", at, {"role": "assistant", "content": topic.reply}))
        history += reply_tokens
    return conversation


def _tool_output(bot, name: str, tool_input: dict) -> str:
    """What the real tool answers today, so the card is the one it would draw."""
    with local.serving(bot, None):
        return str(CATALOGUE[name].call(tool_input))


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

    if not settings.mysql_url or not settings.redis_url:
        print("MYSQL_URL and REDIS_URL must both be set: the console reads names from Redis.")
        return 2

    customers = [] if args.clear else plan(time.time(), random.Random())
    try:
        counts = reseed(customers)
    except Exception as failure:
        # The MySQL half is one transaction and rolls back whole; a failure after
        # its commit (Redis) leaves tonight's rows in place with stale names.
        print(f"Seed failed: {failure}")
        return 1
    if not _profiles_landed(customers):
        print("Rows were written but the names did not reach Redis; the console will show keys, not names.")
        return 1

    print(f"Cleared:   {counts.cleared_rows} rows, {counts.cleared_profiles} profiles")
    print(
        f"Seeded:    {counts.customers} customers, {counts.messages} messages,"
        f" {counts.tool_calls} tool calls, {counts.usage} model calls"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
