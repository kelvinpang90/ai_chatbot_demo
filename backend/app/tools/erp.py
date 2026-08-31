from __future__ import annotations

import json
import logging

from anthropic import beta_tool

from app.services import erp_client
from app.services.api_client import ApiClientError

logger = logging.getLogger(__name__)

# What a tool says when the back office is unreachable. It is phrased for the model
# to relay, not for a log: the honest answer to "got stock or not" is "I could not
# check", and a bot that says so is worth more than one that guesses.
UNAVAILABLE = "The ERP system could not be reached, so this could not be checked."
NOT_FOUND = "No matching product found in the ERP system."


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
    except (ApiClientError, OSError):
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
    except (ApiClientError, OSError):
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


TOOLS = [erp_search_sku, erp_get_inventory]
