"""Nasi Lemak Express: the cart, the order, the kitchen's timeline (task 25).

Driven against an in-memory stand-in for the store, like the property vertical's
tests and for the same reason: `test_verticals_db.py` already checks the SQL
reaches the wire as written. What these check is what sits above it -- that the
price is the menu's, that the order is the customer's and not whoever the model
names, that a database which is down cannot become "your order is placed", and
that the push saying the food has left cannot arrive before the back office
says so.
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.bots.registry import get_bot
from app.config import settings
from app.main import app
from app.services import notify
from app.services.user_store import user_store
from app.tools import food, local, registry
from app.verticals.db import StoreUnavailable
from app.verticals.food import models

TOKEN = "s3cret-console-token"

# Scene 4b's order: 两份椰浆饭一杯拉茶.
SCENE_4B = [{"item_id": "F01", "quantity": 2}, {"item_id": "F08", "quantity": 1}]


class FakeStore:
    """Enough of MySQL for the three statements `food/models.py` writes."""

    def __init__(self, fails: bool = False):
        self.orders: list[dict] = []
        self.fails = fails

    def execute(self, sql: str, params: tuple = ()) -> int:
        if self.fails:
            raise StoreUnavailable("the verticals database is unreachable")
        keys = (
            "customer_key", "customer_name", "phone", "delivery_address", "order_lines",
            "subtotal_rm", "delivery_fee_rm", "total_rm",
            "placed_at", "preparing_at", "ready_at", "delivered_at",
        )
        row = dict(zip(keys, params))
        for column in ("subtotal_rm", "delivery_fee_rm", "total_rm"):
            row[column] = Decimal(row[column])
        for column in ("placed_at", "preparing_at", "ready_at", "delivered_at"):
            row[column] = datetime.strptime(row[column], "%Y-%m-%d %H:%M:%S.%f")
        row["id"] = len(self.orders) + 1
        self.orders.append(row)
        return row["id"]

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.fails:
            raise StoreUnavailable("the verticals database is unreachable")
        rows = sorted(self.orders, key=lambda row: (row["placed_at"], row["id"]), reverse=True)
        if "WHERE customer_key" in sql:
            rows = [row for row in rows if row["customer_key"] == params[0]]
        return [dict(row) for row in rows[: params[-1]]]


@pytest.fixture
def fake_store():
    store = FakeStore()
    with patch.object(models, "store", store):
        yield store


@pytest.fixture
def dead_store():
    store = FakeStore(fails=True)
    with patch.object(models, "store", store):
        yield store


@pytest.fixture
def customer():
    profile = user_store.get_or_create("60129993050")
    profile.display_name = "Aisyah"
    return profile


@pytest.fixture
def on_whatsapp(customer):
    """A turn on the WhatsApp line: a customer, and a push queue that is open."""
    notify.begin()
    with local.serving(get_bot("food"), customer):
        yield customer
    notify.close()


@pytest.fixture
def on_the_web(customer):
    """The web chat line: same customer record, no phone to buzz."""
    with local.serving(get_bot("food"), customer):
        yield customer


def _queued() -> list[notify.Push]:
    return list(notify._pending.get() or [])


# --- the menu -----------------------------------------------------------------


def test_every_dish_has_its_own_id_and_a_price():
    """The model orders by id; two dishes sharing one would be a wrong plate."""
    menu = get_bot("food").context_data["menu"]
    ids = [row["item_id"] for row in menu]

    assert len(ids) == len(set(ids)) == len(food._menu())
    assert get_bot("food").context_data["delivery_fee_rm"] == 5.0


def test_the_food_bot_has_the_ordering_tools():
    names = [tool.name for tool in registry.get_tools("food")]
    assert {"food_update_cart", "food_place_order", "food_order_status"} <= set(names)


# --- the cart -----------------------------------------------------------------


def test_scene_4b_is_priced_from_the_menu_with_delivery_on_top(on_whatsapp):
    """2 x 12.90 + 4.50 = 30.30, plus RM 5 delivery. Worked out in Decimal: a
    float sum of these prices is 30.299999999999997."""
    said = food.food_update_cart(SCENE_4B)

    assert '"subtotal": "RM 30.30"' in said
    assert '"total": "RM 35.30"' in said
    assert on_whatsapp.profile["food"]["cart"] == {"F01": 2, "F08": 1}


def test_a_quantity_is_the_total_wanted_so_saying_it_twice_changes_nothing(on_whatsapp):
    """Absolute, not additive. A retried call -- or a model that repeats itself
    -- must not turn two plates into four."""
    food.food_update_cart(SCENE_4B)
    food.food_update_cart(SCENE_4B)

    assert on_whatsapp.profile["food"]["cart"] == {"F01": 2, "F08": 1}


def test_other_dishes_are_left_alone_and_zero_takes_one_out(on_whatsapp):
    food.food_update_cart(SCENE_4B)
    food.food_update_cart([{"item_id": "F08", "quantity": 0}, {"item_id": "F10", "quantity": 1}])

    assert on_whatsapp.profile["food"]["cart"] == {"F01": 2, "F10": 1}


def test_a_dish_not_on_the_menu_changes_nothing(on_whatsapp):
    food.food_update_cart(SCENE_4B)
    said = food.food_update_cart([{"item_id": "F03", "quantity": 1}, {"item_id": "PIZZA", "quantity": 1}])

    assert "PIZZA is not on the menu" in said
    # Not even the dish that did exist: half an update is a cart nobody asked for.
    assert on_whatsapp.profile["food"]["cart"] == {"F01": 2, "F08": 1}


@pytest.mark.parametrize("quantity", [-1, food.MAX_QUANTITY + 1, True, 2.5])
def test_a_quantity_that_cannot_be_right_changes_nothing(on_whatsapp, quantity):
    said = food.food_update_cart([{"item_id": "F01", "quantity": quantity}])

    assert said.startswith("Nothing was changed")
    assert "cart" not in on_whatsapp.profile["food"]


def test_outside_a_conversation_there_is_no_cart():
    assert food.food_update_cart(SCENE_4B) == food.NO_TURN


# --- placing it ---------------------------------------------------------------


def test_scene_4b_lands_in_the_back_office(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)
    said = food.food_place_order("12 Jalan Ampang, KL")

    (row,) = fake_store.orders
    assert '"order_no": "FD-00001"' in said and "RM 35.30" in said
    assert row["total_rm"] == Decimal("35.30")
    assert row["delivery_address"] == "12 Jalan Ampang, KL"
    # The name on file when the model was not given one.
    assert row["customer_name"] == "Aisyah"
    assert [line["name"] for line in json.loads(row["order_lines"])] == [
        "Nasi Lemak Special",
        "Teh Tarik",
    ]


def test_the_order_is_filed_under_the_customer_in_the_conversation(fake_store, on_whatsapp):
    """Not under anything the model says: "where is my order" is looked up by
    this key, and the model must not be able to name somebody else's."""
    on_whatsapp.phone = "+60 12-999 3050"
    food.food_update_cart(SCENE_4B)
    food.food_place_order("12 Jalan Ampang")

    assert fake_store.orders[0]["customer_key"] == on_whatsapp.key_id
    assert fake_store.orders[0]["phone"] == "+60 12-999 3050"


def test_placing_empties_the_cart_and_remembers_the_address(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)
    food.food_place_order("12 Jalan Ampang")

    assert on_whatsapp.profile["food"]["cart"] == {}
    assert on_whatsapp.profile["food"]["delivery_address"] == "12 Jalan Ampang"
    assert '"delivery_address_on_file": "12 Jalan Ampang"' in food.food_update_cart(SCENE_4B)


def test_the_price_is_the_menus_at_the_moment_of_ordering(fake_store, on_whatsapp):
    """The cart holds quantities only, so a price cannot be smuggled in with it."""
    food.food_update_cart(SCENE_4B)
    menu = {**food._menu()}
    menu["F01"] = {**menu["F01"], "price_rm": 13.90}
    with patch.object(food, "_menu", return_value=menu):
        food.food_place_order("12 Jalan Ampang")

    assert fake_store.orders[0]["total_rm"] == Decimal("37.30")


def test_an_empty_cart_places_nothing(fake_store, on_whatsapp):
    assert food.food_place_order("12 Jalan Ampang") == food.EMPTY_CART
    assert fake_store.orders == []


def test_no_address_places_nothing(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)

    assert food.food_place_order("   ") == food.NEED_ADDRESS
    assert fake_store.orders == []


def test_a_store_that_is_down_is_never_an_order_and_the_cart_survives(dead_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)

    assert food.food_place_order("12 Jalan Ampang") == food.NOT_PLACED
    assert on_whatsapp.profile["food"]["cart"] == {"F01": 2, "F08": 1}
    assert _queued() == []


# --- scene 3: the push, and the timeline it has to agree with -----------------


def test_the_order_queues_the_push_for_the_moment_it_leaves_the_kitchen(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)
    with patch.object(settings, "push_delay_seconds", 30.0):
        food.food_place_order("12 Jalan Ampang")

    (push,) = _queued()
    row = fake_store.orders[0]
    assert push.delay_seconds == (row["ready_at"] - row["placed_at"]).total_seconds() == 30.0
    assert "FD-00001" in push.text and f"{models.RIDER_MINUTES} 分钟" in push.text
    # No template: a kitchen update a day late is not news.
    assert push.template is None


def test_the_kitchen_push_is_in_the_language_the_customer_writes_in(fake_store, on_whatsapp):
    """Task 38.1: scene 3's buzz, in English for someone who ordered in English."""
    on_whatsapp.language = "en"
    food.food_update_cart(SCENE_4B)
    food.food_place_order("12 Jalan Ampang")

    (push,) = _queued()
    assert "left the kitchen" in push.text and "FD-00001" in push.text
    assert " / " not in push.text


def test_when_the_push_can_arrive_the_back_office_already_says_on_the_way(fake_store, on_whatsapp):
    """The one thing this design exists for. The push is dispatched after the
    reply, so it lands at ready_at or later -- and from ready_at the row reads
    on_the_way, with nothing else having to happen."""
    food.food_update_cart(SCENE_4B)
    food.food_place_order("12 Jalan Ampang")
    row = fake_store.orders[0]

    assert models.status_at(row, row["ready_at"]) == models.ON_THE_WAY
    assert models.status_at(row, row["ready_at"] - timedelta(milliseconds=1)) == models.PREPARING


def test_the_web_line_places_the_order_but_promises_no_message(fake_store, on_the_web):
    food.food_update_cart(SCENE_4B)
    said = food.food_place_order("12 Jalan Ampang")

    assert len(fake_store.orders) == 1
    assert "Do not promise them a message" in said
    assert not notify.available()


# --- the timeline -------------------------------------------------------------


def test_an_order_walks_through_all_four_stages():
    stages = models.timeline(1_000_000.0, 30.0)
    row = {key: datetime.fromtimestamp(value) for key, value in stages.items()}
    placed = row["placed_at"]

    seen = [
        models.status_at(row, placed + timedelta(seconds=seconds))
        for seconds in (0, 10, 30, 30 + 60 * models.RIDER_MINUTES)
    ]
    assert seen == [models.RECEIVED, models.PREPARING, models.ON_THE_WAY, models.DELIVERED]


def test_a_rehearsal_with_a_short_delay_still_has_every_stage_in_order():
    """PUSH_DELAY_SECONDS=4 in a rehearsal must not put "preparing" after
    "on its way"."""
    stages = models.timeline(0.0, 4.0)
    assert stages["placed_at"] < stages["preparing_at"] < stages["ready_at"] < stages["delivered_at"]


# --- where is my order --------------------------------------------------------


def test_status_is_read_off_the_timeline(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)
    with patch.object(settings, "push_delay_seconds", 30.0):
        food.food_place_order("12 Jalan Ampang")
    row = fake_store.orders[0]

    with patch.object(models, "datetime", wraps=datetime) as clock:
        clock.now.return_value = row["ready_at"] + timedelta(minutes=4)
        clock.fromisoformat = datetime.fromisoformat
        said = food.food_order_status()

    assert '"status": "on_the_way"' in said
    assert '"arrives_in_minutes": 6' in said


def test_status_only_ever_shows_this_customers_orders(fake_store, on_whatsapp):
    fake_store.execute("INSERT", _someone_elses_order())

    assert food.food_order_status() == food.NO_ORDERS


def test_status_with_the_store_down_does_not_guess(dead_store, on_whatsapp):
    assert food.food_order_status() == food.STATUS_UNAVAILABLE


def _someone_elses_order() -> tuple:
    return (
        "60170000000", "Somebody", "", "Elsewhere", "[]", "4.50", "5.00", "9.50",
        "2026-09-14 12:00:00.000", "2026-09-14 12:00:10.000",
        "2026-09-14 12:00:30.000", "2026-09-14 12:10:30.000",
    )


# --- the back office ----------------------------------------------------------


def _get(http, **headers):
    return http.get("/api/verticals/food/orders", headers=headers)


def test_the_back_office_shows_the_order_and_its_stage(fake_store, on_whatsapp):
    food.food_update_cart(SCENE_4B)
    food.food_place_order("12 Jalan Ampang")

    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            (order,) = _get(http, **{"X-Console-Token": TOKEN}).json()

    assert order["order_no"] == "FD-00001"
    assert order["status"] == models.RECEIVED
    assert [line["quantity"] for line in order["lines"]] == [2, 1]
    assert order["total_rm"] == 35.3
    # Naive, for the page to slice; see tasks/erp-crm-timezone.md.
    assert "Z" not in order["ready_at"] and "+" not in order["ready_at"]


def test_a_back_office_that_is_down_answers_503_not_an_empty_list(dead_store):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http, **{"X-Console-Token": TOKEN}).status_code == 503


def test_the_back_office_is_closed_without_the_token_in_the_header(fake_store):
    with patch.object(settings, "console_token", TOKEN):
        with TestClient(app) as http:
            assert _get(http).status_code == 401
            assert http.get("/api/verticals/food/orders", params={"token": TOKEN}).status_code == 401
