from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services import phone
from app.services.api_client import JsonApiClient

# The VPS runs on UTC and the shop does not. Between midnight and 8am local time
# `date.today()` would date an order to yesterday, which is what the customer and
# the salesperson both see on screen. Malaysia has no daylight saving, so a fixed
# offset is exact rather than an approximation.
MALAYSIA_TIME = timezone(timedelta(hours=8))

# A customer asking about stock wants the two or three products they mean, not a
# catalogue page. Keeping the result small also keeps the console readable.
DEFAULT_RESULT_LIMIT = 5

# Orders taken over WhatsApp ship from the main branch unless the caller names
# another warehouse -- erp_get_inventory hands the model real warehouse ids, so
# it can pick the branch that actually has the stock.
DEFAULT_WAREHOUSE_ID = 1


class ErpClient(JsonApiClient):
    """erp_os over its own REST routes.

    Deliberately not straight to MySQL: writes have to go through the business
    logic or the back office fills up with rows the ERP itself considers invalid,
    and reads should see exactly what the screen behind us is showing.
    """

    def __init__(self) -> None:
        super().__init__(
            name="erp",
            base_url=settings.erp_base_url,
            email=settings.erp_email,
            password=settings.erp_password,
        )

    def search_skus(self, keyword: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Products matching a name or code fragment."""
        payload = self.get("/api/skus", params={"search": keyword, "page_size": limit})
        return payload.get("items", [])

    def branch_inventory(self, sku_query: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Stock for the matching SKUs, one row per SKU, broken down by warehouse.

        `/api/inventory/stocks` would be the more obvious route but it demands a
        warehouse_id, and a customer asking "got stock or not" means across the
        whole shop. The matrix answers that in one call.
        """
        payload = self.get(
            "/api/inventory/branch-matrix",
            params={"sku_query": sku_query, "page_size": limit},
        )
        return payload.get("rows", [])

    def sku(self, sku_id: int) -> dict:
        """One product, including the fields an order line needs."""
        return self.get(f"/api/skus/{sku_id}")

    def find_customers(self, term: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Customers matching a name, code, contact person, email or phone.

        An order needs an erp_os customer id, and erp_os ids have nothing to do
        with crm_os's, so this is the only honest source of one.

        `?search=` covers code, name, contact_person and email but not phone
        (`repositories/customer.py:55-64`) -- the same gap crm_os has. The one
        identifier a WhatsApp conversation always carries is the phone number, so
        that case pages the book and matches here.
        """
        if phone.looks_like_a_phone(term):
            return self._customers_by_phone(term, limit=limit)
        return self._customers_page(search=term, page_size=limit)

    def _customers_page(
        self, *, search: str | None = None, page: int = 1, page_size: int = phone.PAGE_SIZE
    ) -> list[dict]:
        payload = self.get(
            "/api/customers",
            params={"search": search, "page": page, "page_size": page_size},
        )
        return payload.get("items", [])

    def _customers_by_phone(self, term: str, *, limit: int) -> list[dict]:
        matches: list[dict] = []
        for page in range(1, phone.MAX_SCAN_PAGES + 1):
            rows = self._customers_page(page=page)
            for row in rows:
                if phone.matches(row.get("phone", ""), term):
                    matches.append(row)
                    if len(matches) >= limit:
                        return matches
            if len(rows) < phone.PAGE_SIZE:
                break
        return matches

    def create_sales_order(
        self,
        *,
        customer_id: int,
        lines: list[tuple[int, float]],
        warehouse_id: int = DEFAULT_WAREHOUSE_ID,
    ) -> dict:
        """Book a DRAFT sales order for (sku_id, qty) pairs.

        erp_os wants a unit of measure, a tax rate and a price on every line; the
        caller supplies neither. That is deliberate -- see `_line`.
        """
        payload = {
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "business_date": datetime.now(MALAYSIA_TIME).date().isoformat(),
            "lines": [self._line(sku_id, qty) for sku_id, qty in lines],
        }
        return self.post("/api/sales-orders", json=payload)

    def _line(self, sku_id: int, qty: float) -> dict:
        """One order line, priced from the catalogue rather than by the caller.

        The model is holding the conversation, not the price list. If it could
        pass a unit price, a customer who asked nicely for a discount would get a
        real order booked at a made-up number -- and the salesperson watching the
        console would have no way to tell that from a real promotion.
        """
        sku = self.sku(sku_id)
        return {
            "sku_id": sku_id,
            "uom_id": sku["base_uom_id"],
            "tax_rate_id": sku["tax_rate_id"],
            "qty_ordered": str(qty),
            "unit_price_excl_tax": str(sku["unit_price_excl_tax"]),
        }

    def confirm_sales_order(self, so_id: int) -> dict:
        """DRAFT -> CONFIRMED, which is the step that reserves the stock.

        Until this runs the order is a piece of paper: the warehouse screen still
        shows every unit as available and erp_os will not let it be shipped or
        invoiced.
        """
        return self.post(f"/api/sales-orders/{so_id}/confirm")


_client: ErpClient | None = None


def client() -> ErpClient:
    """One process-wide client, so the cached token is actually shared."""
    global _client
    if _client is None:
        _client = ErpClient()
    return _client


def reset() -> None:
    """Drop the cached client. For tests."""
    global _client
    _client = None
