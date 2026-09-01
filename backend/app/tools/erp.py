from __future__ import annotations

import json
import logging
from typing import TypedDict

from anthropic import beta_tool

from app.services import erp_client
from app.services.api_client import ApiClientError

logger = logging.getLogger(__name__)

# What a tool says when the back office is unreachable. It is phrased for the model
# to relay, not for a log: the honest answer to "got stock or not" is "I could not
# check", and a bot that says so is worth more than one that guesses.
UNAVAILABLE = "The ERP system could not be reached, so this could not be checked."
NOT_FOUND = "No matching product found in the ERP system."

# A write needs its own vocabulary. "Could not be checked" is the wrong thing to
# tell someone who is waiting to hear whether their order went in, and the two
# failures below are different enough that the customer deserves to know which
# one happened.
ORDER_FAILED = (
    "The order could not be created in the ERP system. Nothing was booked -- "
    "tell the customer their order was not placed."
)
# The write went out and no answer came back. Claiming either outcome here is a
# guess, and the two guesses are not equally cheap: told "it failed", a customer
# reorders, and now there are two real orders for one intent.
ORDER_UNKNOWN = (
    "The ERP system stopped responding while the order was being placed, so it "
    "is NOT known whether the order exists. Do not place it again. Tell the "
    "customer their order is being checked and a colleague will confirm it "
    "within a few minutes."
)
BAD_ITEMS = (
    "The order items were not in the expected shape. Each one needs a numeric "
    "sku_id from erp_search_sku and a quantity greater than zero."
)
NO_CUSTOMER = (
    "No matching customer found in the ERP system. An order needs an existing "
    "ERP customer -- do not invent a customer_id, ask the customer for the name "
    "or company the account is under."
)


def _not_confirmed(document_no: str) -> str:
    """The half-done case: the order exists but holds no stock.

    Silence here would be the worst outcome of the three -- a salesperson who
    believes an order is live, and a warehouse that has not set anything aside.
    The ERP refused the confirmation for a reason it will keep refusing (usually
    not enough stock in that branch), so this does not promise it will clear on
    its own.
    """
    return (
        f"Order {document_no} was created but the ERP REFUSED to confirm it, so no "
        "stock is reserved and it cannot be shipped or invoiced. The order is "
        "sitting as a draft for a colleague to sort out -- most often this means "
        "the branch does not have enough stock. Tell the customer their order is "
        "on hold and someone will call them back."
    )


def _confirmation_unknown(document_no: str) -> str:
    """The order is real; whether the stock was reserved is not known."""
    return (
        f"Order {document_no} was created, but the ERP stopped responding before "
        "it confirmed whether the stock was reserved. Do not create the order "
        "again. Tell the customer the order is placed and a colleague is "
        "confirming the details."
    )


def _as_json(rows: list) -> str:
    return json.dumps(rows, ensure_ascii=False, default=str)


def _price(sku: dict) -> str:
    """Whichever of the two prices the SKU is actually sold at."""
    key = "unit_price_incl_tax" if sku.get("price_tax_inclusive") else "unit_price_excl_tax"
    return str(sku.get(key))


@beta_tool
def erp_search_sku(keyword: str) -> str:
    """Search the ERP product catalogue by name or product code.

    Use this to find a product the customer mentions before quoting a price or
    checking stock. Returns the product code, name and unit price.

    Args:
        keyword: Part of a product name or code, e.g. "earbuds" or "SKU-00012".
    """
    try:
        skus = erp_client.client().search_skus(keyword)
    except ApiClientError:
        logger.exception("erp_search_sku failed for %r", keyword)
        return UNAVAILABLE

    if not skus:
        return NOT_FOUND

    # The catalogue row carries ~30 columns; the model needs the handful a customer
    # would ask about, and the console screen has to stay readable.
    return _as_json(
        [
            {
                "sku_id": sku.get("id"),
                "code": sku.get("code"),
                "name": sku.get("name"),
                "name_zh": sku.get("name_zh"),
                "unit_price": _price(sku),
                "currency": sku.get("currency"),
            }
            for sku in skus
        ]
    )


@beta_tool
def erp_get_inventory(sku: str) -> str:
    """Check live stock levels for a product, broken down by warehouse.

    Use this whenever the customer asks whether something is available or how many
    are left. "available" is what can actually be sold: on-hand minus what is
    already reserved for other orders.

    Args:
        sku: A product code or part of a product name, e.g. "SKU-00012" or "earbuds".
    """
    try:
        rows = erp_client.client().branch_inventory(sku)
    except ApiClientError:
        logger.exception("erp_get_inventory failed for %r", sku)
        return UNAVAILABLE

    if not rows:
        return NOT_FOUND

    return _as_json(
        [
            {
                "sku_id": row.get("sku_id"),
                "code": row.get("sku_code"),
                "name": row.get("sku_name"),
                "total_available": sum(
                    float(cell.get("available") or 0) for cell in row.get("warehouses", [])
                ),
                "by_warehouse": [
                    {
                        "warehouse_id": cell.get("warehouse_id"),
                        "warehouse": cell.get("warehouse_name"),
                        "available": cell.get("available"),
                    }
                    for cell in row.get("warehouses", [])
                ],
            }
            for row in rows
        ]
    )


@beta_tool
def erp_find_customer(name_or_phone: str) -> str:
    """Find the customer account an order should be billed to, in the ERP.

    Call this before erp_create_sales_order: the customer_id that order needs
    comes from here and nowhere else. A CRM contact id is a different system's
    identifier and will book the order onto the wrong account. If nothing comes
    back, say so -- never guess an id.

    Args:
        name_or_phone: The customer or company name, or a phone number in any
            format.
    """
    try:
        customers = erp_client.client().find_customers(name_or_phone)
    except ApiClientError:
        logger.exception("erp_find_customer failed for %r", name_or_phone)
        return UNAVAILABLE

    if not customers:
        return NO_CUSTOMER

    return _as_json(
        [
            {
                "customer_id": customer.get("id"),
                "code": customer.get("code"),
                "name": customer.get("name"),
                "phone": customer.get("phone"),
                "currency": customer.get("currency"),
            }
            for customer in customers
        ]
    )


class OrderLine(TypedDict):
    """One line of a sales order. Price and tax come from the catalogue."""

    sku_id: int
    quantity: float


@beta_tool
def erp_create_sales_order(
    customer_id: int,
    items: list[OrderLine],
    warehouse_id: int = erp_client.DEFAULT_WAREHOUSE_ID,
) -> str:
    """Create a real sales order in the ERP and confirm it, reserving the stock.

    This writes to the live back office, so only call it once the customer has
    agreed to the products and quantities. Check stock with erp_get_inventory
    first. Prices are taken from the catalogue, never from the conversation.

    The customer_id must come from erp_find_customer. Never guess one and never
    reuse an id from the CRM: every integer is some real customer's account, so a
    guess bills a stranger and nobody notices.

    Args:
        customer_id: The ERP customer this order belongs to, as returned by
            erp_find_customer. Every integer is somebody's real account, so a
            guessed one silently bills a stranger -- if erp_find_customer found
            nobody, do not call this tool.
        items: The products being ordered, each with a sku_id from erp_search_sku
            and a quantity.
        warehouse_id: The branch to ship from, as returned by erp_get_inventory.
            Defaults to the main warehouse.
    """
    try:
        lines = [(int(item["sku_id"]), float(item["quantity"])) for item in items]
    except (KeyError, TypeError, ValueError):
        logger.warning("erp_create_sales_order got unusable items: %r", items)
        return BAD_ITEMS

    # An empty order and a zero quantity both come back from erp_os as a 422 the
    # model cannot act on. Say what is wrong while we still know.
    if not lines or any(qty <= 0 for _, qty in lines):
        return BAD_ITEMS

    client = erp_client.client()
    try:
        order = client.create_sales_order(
            customer_id=customer_id, lines=lines, warehouse_id=warehouse_id
        )
    except ApiClientError as exc:
        logger.exception("erp_create_sales_order failed for customer %s", customer_id)
        # "It failed" and "I do not know" are different instructions to the person
        # on the other end: one of them makes them order again.
        return ORDER_UNKNOWN if exc.may_have_landed else ORDER_FAILED

    document_no = order.get("document_no", "")
    try:
        order = client.confirm_sales_order(order["id"])
    except (ApiClientError, KeyError) as exc:
        logger.exception("confirming sales order %s failed", document_no)
        unknown = isinstance(exc, ApiClientError) and exc.may_have_landed
        return _confirmation_unknown(document_no) if unknown else _not_confirmed(document_no)

    return _as_json(
        {
            "order_no": order.get("document_no"),
            "status": order.get("status"),
            "customer": order.get("customer_name"),
            "warehouse": order.get("warehouse_name"),
            "currency": order.get("currency"),
            "total_incl_tax": order.get("total_incl_tax"),
            "lines": [
                {
                    "code": line.get("sku_code"),
                    "name": line.get("sku_name"),
                    "qty": line.get("qty_ordered"),
                    "unit_price": line.get("unit_price_excl_tax"),
                    "line_total_incl_tax": line.get("line_total_incl_tax"),
                }
                for line in order.get("lines", [])
            ],
        }
    )


TOOLS = [erp_search_sku, erp_get_inventory, erp_find_customer, erp_create_sales_order]
