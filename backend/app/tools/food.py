"""Nasi Lemak Express's ordering tools (task 25).

Scene 4b in three calls: the customer names dishes and the cart is set, they
agree to the total and the order is placed, they ask where it is and the status
is read off the order's own timeline. Scene 3 is the push the order queues on
its way in -- "your food is on its way" -- timed for the moment the back office
starts saying the same thing (see `verticals/food/models.py`).

**The cart lives on the customer's record, the order in the back office.** A
cart is a sentence in progress: it belongs with the conversation, in the slot
the hotel's bookings and the SaaS tickets already use (`local.records()`), and
it is in front of the model on the next turn without asking for it. An order is
what the restaurant has to act on, so it is a row on the screen.

**Prices come from the menu, never from the conversation.** The menu is the
bot's own JSON -- the same data the model quotes from -- and every line is priced
from it when the cart is set and again when the order is placed.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import TypedDict

from anthropic import beta_tool

from app.bots import registry as bots
from app.config import settings
from app.services import notify
from app.services.language import Localized
from app.tools import local
from app.verticals import StoreUnavailable
from app.verticals.food import models

logger = logging.getLogger(__name__)

# Nobody orders fifty plates of nasi lemak over WhatsApp, and the one who
# appears to has had a number misheard. Catering has its own answer in the FAQ.
MAX_QUANTITY = 20

# The in-progress cart, under the customer's slot for this bot: item_id -> quantity.
CART = "cart"
# Kept after an order so the next one does not have to ask again.
ADDRESS = "delivery_address"

# Sent by the push timer, after the model's turn has ended -- so it is canned,
# written in all three languages like every other line the model did not write,
# and sent in the one on the customer's record (task 38.1).
ON_THE_WAY_PUSH = Localized(
    zh="您的订单 {order_no} 已出餐，骑手预计 {minutes} 分钟送达。",
    en="Your order {order_no} has left the kitchen - "
    "the rider should be with you in about {minutes} minutes.",
    ms="Pesanan anda {order_no} sudah siap - penghantar dijangka tiba dalam {minutes} minit.",
)

NO_TURN = (
    "The order could not be taken because this conversation has no customer "
    "record to hold it. Say you cannot take the order here right now and offer "
    "to have a colleague call them back."
)
NO_MENU = (
    "The menu could not be read, so nothing was changed. Do not quote prices or "
    "take the order; say you cannot take orders right now and offer to have a "
    "colleague call them back."
)
EMPTY_CART = (
    "The cart is empty, so nothing was ordered. Ask the customer what they would "
    "like, set the cart with food_update_cart, and tell them the total before "
    "placing anything."
)
NEED_ADDRESS = (
    "Nothing was ordered: there is no delivery address. Ask the customer where "
    "the order is going, in one short line, and place it once they have said."
)
NOT_PLACED = (
    "The order could NOT be placed -- the restaurant's order system is "
    "unreachable. The cart is still there. Tell the customer plainly that it did "
    "not go through and offer to have a colleague call them back. Never tell "
    "them the order is placed and never make up an order number."
)
NO_ORDERS = (
    "This customer has no orders on file. Say so plainly -- never invent an "
    "order number or a delivery time -- and offer to take an order."
)
STATUS_UNAVAILABLE = (
    "The order system could not be reached just now. Say you cannot check the "
    "order at the moment and offer to have a colleague call them back. Do not "
    "guess where it is."
)

STAGE_WORDS = {
    models.RECEIVED: "received -- the kitchen has not started it yet",
    models.PREPARING: "being cooked in the kitchen",
    models.ON_THE_WAY: "on its way with the rider",
    models.DELIVERED: "delivered",
}


class CartItem(TypedDict):
    """One dish and how many of it the customer wants in total."""

    item_id: str
    quantity: int


def _menu() -> dict[str, dict]:
    bot = bots.get_bot("food")
    rows = bot.context_data.get("menu", []) if bot is not None else []
    return {
        str(row["item_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("item_id") and row.get("price_rm") is not None
    }


def _fee() -> Decimal:
    bot = bots.get_bot("food")
    return Decimal(str(bot.context_data.get("delivery_fee_rm", 0) if bot is not None else 0))


def _rm(amount: Decimal) -> str:
    return f"RM {amount.quantize(Decimal('0.01'))}"


def _priced(cart: dict, menu: dict[str, dict]) -> list[models.OrderLine]:
    """The cart as order lines, in menu order, priced from the menu."""
    return [
        models.OrderLine(
            item_id=item_id,
            name=row["name"],
            unit_price_rm=float(row["price_rm"]),
            quantity=int(cart[item_id]),
        )
        for item_id, row in menu.items()
        if int(cart.get(item_id, 0)) > 0
    ]


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


@beta_tool
def food_update_cart(items: list[CartItem]) -> str:
    """Set how many of each dish is in the customer's cart, and get the total back.

    Call it as soon as the customer names dishes -- "two nasi lemak and a teh
    tarik" is two items in one call. The quantity is the TOTAL they now want of
    that dish, not an amount to add: if they already have 2 and say "one more",
    send 3. A quantity of 0 takes the dish out. Dishes not mentioned are left as
    they are.

    This does not place the order. Read the total back to the customer and ask
    them to confirm before calling food_place_order.

    Args:
        items: Each dish by its item_id from the menu (e.g. "F01") and the total
            quantity wanted.
    """
    cart_slot = local.records()
    if cart_slot is None:
        return NO_TURN
    menu = _menu()
    if not menu:
        return NO_MENU

    unknown = [str(item.get("item_id", "")) for item in items if str(item.get("item_id", "")) not in menu]
    if unknown:
        return (
            f"Nothing was changed: {', '.join(unknown) or 'an empty id'} is not on the menu. "
            "Use the item_id of a dish that is on the menu. If the customer asked for "
            "something the restaurant does not make, tell them and suggest the closest dish."
        )
    for item in items:
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 <= quantity <= MAX_QUANTITY:
            return (
                f"Nothing was changed: {quantity!r} is not a quantity this can take "
                f"(0 to {MAX_QUANTITY}). Check the number with the customer."
            )

    cart = dict(cart_slot.get(CART) or {})
    for item in items:
        if item["quantity"] == 0:
            cart.pop(item["item_id"], None)
        else:
            cart[item["item_id"]] = item["quantity"]
    cart_slot[CART] = cart

    lines = _priced(cart, menu)
    if not lines:
        return _dump({"cart": [], "note": "The cart is now empty."})
    subtotal = models.subtotal_of(lines)
    fee = _fee()
    return _dump(
        {
            "cart": [
                {
                    "item_id": line.item_id,
                    "name": line.name,
                    "quantity": line.quantity,
                    "line_total": _rm(Decimal(str(line.unit_price_rm)) * line.quantity),
                }
                for line in lines
            ],
            "subtotal": _rm(subtotal),
            "delivery_fee": _rm(fee),
            "total": _rm(subtotal + fee),
            "delivery_address_on_file": cart_slot.get(ADDRESS) or None,
            "note": (
                "Nothing is ordered yet. Tell the customer what is in the cart and the "
                "total including delivery, and ask them to confirm. If there is no "
                "delivery address on file, ask for it in the same message."
            ),
        }
    )


@beta_tool
def food_place_order(delivery_address: str, customer_name: str = "") -> str:
    """Place the order for what is in the customer's cart. The kitchen starts on it.

    Only call this once the customer has seen the total and said yes. It sends the
    order to the restaurant's back office, where it appears on screen at once, and
    empties the cart.

    Args:
        delivery_address: Where the food is going, as the customer gave it. Use the
            address on file if they confirmed it; if there is none, ask first.
        customer_name: Their name if they have given one. Leave it empty rather
            than guess.
    """
    cart_slot = local.records()
    customer = local.customer()
    if cart_slot is None or customer is None:
        return NO_TURN
    menu = _menu()
    if not menu:
        return NO_MENU
    lines = _priced(dict(cart_slot.get(CART) or {}), menu)
    if not lines:
        return EMPTY_CART
    address = str(delivery_address or "").strip()
    if not address:
        return NEED_ADDRESS

    fee = _fee()
    ready_after = settings.push_delay_seconds
    try:
        placed = models.place_order(
            customer_key=customer.key_id,
            customer_name=str(customer_name or "").strip() or customer.display_name or "",
            phone=customer.phone or "",
            delivery_address=address,
            lines=lines,
            delivery_fee_rm=fee,
            ready_after_seconds=ready_after,
            at=time.time(),
        )
    except StoreUnavailable:
        logger.exception("a food order could not be placed")
        return NOT_PLACED

    order_no = models.order_no(placed)
    cart_slot[CART] = {}
    cart_slot[ADDRESS] = address

    # Queued for the moment the order's own timeline says it leaves the kitchen,
    # so the back office already reads "on its way" when the phone buzzes. No
    # template: a kitchen update a day late is not news, so outside the 24-hour
    # window it is simply not sent.
    will_buzz = notify.available() and notify.add(
        notify.Push(
            delay_seconds=ready_after,
            text=ON_THE_WAY_PUSH.format(order_no=order_no, minutes=models.RIDER_MINUTES).pick(
                local.customer_language()
            ),
        )
    )
    total = models.subtotal_of(lines) + fee
    arrives_in = round((ready_after + models.RIDER_MINUTES * 60) / 60)
    return _dump(
        {
            "order_no": order_no,
            "status": models.RECEIVED,
            "items": [f"{line.quantity} x {line.name}" for line in lines],
            "total": _rm(total),
            "delivery_address": address,
            "note": (
                f"The order IS PLACED as {order_no}, total {_rm(total)}. Confirm it to the "
                "customer in one short message with the order number and the total. "
                + (
                    f"It should arrive in about {arrives_in} minutes, and they will get "
                    "a message by themselves when it leaves the kitchen."
                    if will_buzz
                    else f"It should arrive in about {arrives_in} minutes. Do not promise "
                    "them a message when it leaves: this channel cannot send one."
                )
            ),
        }
    )


@beta_tool
def food_order_status() -> str:
    """Look up where the customer's recent orders are: kitchen, rider, or delivered.

    Call it whenever they ask about an order they have placed -- "where is my
    food", "has it left yet". Only this customer's own orders are ever returned.
    """
    customer = local.customer()
    if customer is None:
        return NO_TURN
    try:
        found = models.orders_for(customer.key_id)
    except StoreUnavailable:
        logger.exception("food order status could not be read")
        return STATUS_UNAVAILABLE
    if not found:
        return NO_ORDERS

    def describe(order: models.Order) -> dict:
        entry = {
            "order_no": order.order_no,
            "status": order.status,
            "meaning": STAGE_WORDS[order.status],
            "items": [f"{line.quantity} x {line.name}" for line in order.lines],
            "total": _rm(Decimal(str(order.total_rm))),
            "placed_at": order.placed_at[:16],
        }
        if order.status in (models.RECEIVED, models.PREPARING):
            entry["leaves_kitchen_in_minutes"] = models.minutes_until(order.ready_at)
        if order.status != models.DELIVERED:
            entry["arrives_in_minutes"] = models.minutes_until(order.delivered_at)
        return entry

    return _dump(
        {
            "orders": [describe(order) for order in found],
            "note": "Newest first. Answer about the order they mean -- usually the first.",
        }
    )


TOOLS = [food_update_cart, food_place_order, food_order_status]
