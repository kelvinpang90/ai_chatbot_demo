from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

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

# Written onto the delivery order so that a row created from a chat is
# distinguishable from one a warehouse clerk keyed in, on the screen the customer
# is being shown.
WHATSAPP_SHIPPING_METHOD = "WhatsApp order"

# erp_os caps the sales order's shipping address at 500 characters
# (`schemas/sales_order.py:68`). Longer is a 422 that loses the whole order, so
# the length is checked before the write rather than discovered after it.
MAX_SHIPPING_ADDRESS_CHARS = 500


class SkuMatches(NamedTuple):
    """One page of matching products, and how many the ERP found in all.

    `total` is the ERP's own count over the whole catalogue, so it can be
    larger than `items` -- that gap is the thing worth carrying: it is the
    difference between "we stock these five" and "here are five of eight".
    """

    items: list[dict]
    total: int


def _is_the_same_document(found: str, wanted: str) -> bool:
    """Two document numbers written the same way, allowing for how they were typed.

    Deliberately no looser than that: this decides which order gets shipped, and
    a substring rule here would let SO-2026-0042 select SO-2026-00420.
    """
    return str(found).strip().casefold() == wanted.strip().casefold()


def _outstanding(line: dict) -> Decimal:
    """How much of an order line has not shipped yet.

    Quantities arrive as DECIMAL strings ("3.0000"), and erp_os rejects a
    shipment larger than what is left, so the arithmetic is done exactly rather
    than through float.
    """
    try:
        ordered = Decimal(str(line.get("qty_ordered", 0)))
        shipped = Decimal(str(line.get("qty_shipped", 0)))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
    return ordered - shipped


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

    def search_skus(self, keyword: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> SkuMatches:
        """Products matching a name or code fragment, and how many matched in all.

        The count used to be thrown away with the rest of the envelope, and that
        is the whole reason for this shape: a page of five out of eight looks
        exactly like a shop that stocks five, so the bot told customers it had
        shown them everything.
        """
        payload = self.get("/api/skus", params={"search": keyword, "page_size": limit})
        items = payload.get("items", [])
        # A missing count falls back to what did arrive rather than to zero:
        # claiming "0 matches" while holding five of them is the one answer that
        # is certainly wrong.
        try:
            total = int(payload.get("total"))
        except (TypeError, ValueError):
            total = len(items)
        return SkuMatches(items=items, total=max(total, len(items)))

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

    def create_customer(
        self,
        *,
        code: str,
        name: str,
        phone: str,
        contact_person: str | None = None,
        is_business: bool = False,
        tin: str | None = None,
        address_line1: str | None = None,
        city: str | None = None,
        postcode: str | None = None,
    ) -> dict:
        """Open a trade account, so a walk-in can be sold to like anyone else.

        Only `code` and `name` are required by erp_os, but a record with nothing
        else on it is one a salesperson cannot act on and `find_customers` cannot
        find: its phone scan reads the `phone` column, so an account created
        without a number is invisible to the next conversation from that number.

        `customer_type` is not cosmetic. erp_os pre-validates an e-Invoice
        against LHDN's rules, and a B2B buyer with no TIN fails them where a B2C
        buyer without one passes. Someone who gave no company name is an
        individual, and saying so keeps their invoice clean.
        """
        payload: dict = {
            "code": code,
            "name": name,
            "phone": phone,
            "customer_type": "B2B" if is_business else "B2C",
        }
        # Sent only where the conversation actually produced one: an empty string
        # in the ERP reads as a field someone cleared, not one never filled in.
        for field, value in (
            ("contact_person", contact_person),
            ("tin", tin),
            ("address_line1", address_line1),
            ("city", city),
            ("postcode", postcode),
        ):
            if value:
                payload[field] = value
        return self.post("/api/customers", json=payload)

    def create_sales_order(
        self,
        *,
        customer_id: int,
        lines: list[tuple[int, float]],
        warehouse_id: int = DEFAULT_WAREHOUSE_ID,
        shipping_address: str = "",
    ) -> dict:
        """Book a DRAFT sales order for (sku_id, qty) pairs.

        erp_os wants a unit of measure, a tax rate and a price on every line; the
        caller supplies neither. That is deliberate -- see `_line`.

        The address is sent only when there is one. Sending an explicit null
        would overwrite nothing today, but it also says something the caller does
        not know: that this customer has no delivery address, rather than that
        this conversation did not mention one.
        """
        payload = {
            "customer_id": customer_id,
            "warehouse_id": warehouse_id,
            "business_date": datetime.now(MALAYSIA_TIME).date().isoformat(),
            "lines": [self._line(sku_id, qty) for sku_id, qty in lines],
        }
        if shipping_address:
            payload["shipping_address"] = shipping_address
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

    def recent_orders(self, customer_id: int, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """The customer's own orders, newest first.

        erp_os sorts by business date then id, both descending
        (`repositories/sales_order.py:78`), so "newest first" is the ERP's doing
        rather than an assumption made here. Scoped to one customer for the same
        reason `sales_order_for_customer` is: this id decides whose order history
        gets read out loud in somebody's chat.
        """
        payload = self.get(
            "/api/sales-orders",
            params={"customer_id": customer_id, "page_size": limit},
        )
        return payload.get("items", [])

    def sales_order_for_customer(self, document_no: str, customer_id: int) -> dict | None:
        """The customer's own order with that number, in full, or None.

        Scoped to the customer on purpose. The order number reaches this client
        from the model, which read it out of an earlier tool result but could
        equally have made it up, and the id it resolves to decides whose stock
        moves and whose invoice is sent to this phone. Filtering the query by the
        customer erp_find_customer identified means a number the model invented
        finds nothing instead of finding somebody else's order.

        `?search=` is a LIKE on document_no and remarks, so the exact number is
        matched here rather than trusted from the query -- SO-2026-0042 also
        answers for SO-2026-00420, and only one of those is the customer's.

        Exact on the number, not on the spelling. erp_os matches case
        insensitively, so a compare stricter than the ERP's own would throw away
        a row the ERP had already found and tell the customer their order does
        not exist. The number is trimmed on the way out too, or the LIKE goes
        looking for a leading space that is not in any document number.
        """
        wanted = str(document_no).strip()
        payload = self.get(
            "/api/sales-orders",
            params={
                "search": wanted,
                "customer_id": customer_id,
                "page_size": DEFAULT_RESULT_LIMIT,
            },
        )
        row = next(
            (
                item
                for item in payload.get("items", [])
                if _is_the_same_document(item.get("document_no", ""), wanted)
            ),
            None,
        )
        return None if row is None else self.sales_order(row["id"])

    def sales_order(self, so_id: int) -> dict:
        """One order with its lines, which is what shipping and invoicing need."""
        return self.get(f"/api/sales-orders/{so_id}")

    def ship_sales_order(self, so: dict) -> dict:
        """Ship everything still outstanding on the order, in one delivery.

        erp_os will not invoice an order that has not shipped
        (`services/einvoice.py:245` wants PARTIAL_SHIPPED or FULLY_SHIPPED), and
        for a WhatsApp order paid on delivery the shipment is the step nobody is
        going to perform by hand in the middle of a conversation.
        """
        lines = [
            {"sales_order_line_id": line["id"], "qty_shipped": str(remaining)}
            for line, remaining in ((line, _outstanding(line)) for line in so.get("lines", []))
            if remaining > 0
        ]
        return self.post(
            "/api/delivery-orders",
            json={
                "sales_order_id": so["id"],
                "delivery_date": datetime.now(MALAYSIA_TIME).date().isoformat(),
                "shipping_method": WHATSAPP_SHIPPING_METHOD,
                "lines": lines,
            },
        )

    def invoice_for_order(self, so_id: int) -> dict | None:
        """The invoice already raised against an order, in full, or None.

        Asked before anything is shipped, because an order that has been billed
        before must not be billed again -- and because half the orders in the
        demo database are seeded as INVOICED with a real invoice attached
        (`erp_os/backend/scripts/seed_transactional.py:267`). A customer asking
        for one of those wants the document that exists, not a refusal.

        erp_os allows at most one invoice per sales order, so the first row is
        the row.
        """
        payload = self.get("/api/invoices", params={"sales_order_id": so_id, "page_size": 1})
        items = payload.get("items", [])
        return None if not items else self.invoice(items[0]["id"])

    def invoice(self, invoice_id: int) -> dict:
        """One invoice with its lines, which is what the PDF is drawn from."""
        return self.get(f"/api/invoices/{invoice_id}")

    def invoice_for_sales_order(self, so_id: int) -> dict:
        """The e-Invoice for a shipped order, created if it does not exist yet.

        Idempotent at the far end: erp_os returns the existing invoice rather
        than a second one, so calling this twice cannot bill the customer twice.
        """
        return self.post(f"/api/invoices/generate-from-so/{so_id}", json={})

    def submit_invoice(self, invoice_id: int) -> dict:
        """DRAFT -> VALIDATED, which is what puts an LHDN UIN on the document.

        Without it the customer receives a printout; with it they receive the
        thing Malaysian businesses have to file from August 2024 onwards.
        """
        return self.post(f"/api/invoices/{invoice_id}/submit")


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
