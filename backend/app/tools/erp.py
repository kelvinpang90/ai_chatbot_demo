from __future__ import annotations

import json
import logging
from typing import TypedDict

from anthropic import beta_tool

from app.services import erp_client, invoice_pdf, outbox, whatsapp_media
from app.services.api_client import ApiClientError
from app.services.whatsapp_media import MediaError

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


# The statuses an order can be invoiced from. Anything else is either not yet
# agreed (DRAFT) or no longer an order at all (CANCELLED).
INVOICEABLE = ("CONFIRMED", "PARTIAL_SHIPPED", "FULLY_SHIPPED")
SHIPPED = "FULLY_SHIPPED"
INVOICE_DRAFT = "DRAFT"

PDF_MIME = "application/pdf"

NO_SUCH_ORDER = (
    "No order with that number belongs to this customer, so no invoice was "
    "issued. Use the order number erp_create_sales_order returned and the "
    "customer_id from erp_find_customer -- do not guess either."
)
# Every step below is guarded by the state it reads first, so calling this tool
# again cannot ship twice, invoice twice or submit twice. That is why there is one
# failure message here and not the certain/uncertain pair the order and lead tools
# carry: the distinction those two draw exists to stop a retry duplicating a
# write, and here a retry cannot.
INVOICE_FAILED = (
    "The invoice could not be issued. The customer's order itself is unaffected "
    "-- it is still placed. Trying once more is safe. If it fails again, tell "
    "the customer their invoice will follow shortly and a colleague will send it."
)
# The invoice exists in the ERP by this point. Saying it failed would be untrue
# and would send the model back to issue another one.
PDF_NOT_SENT = (
    "The invoice was issued but the PDF could not be delivered in this chat. Give "
    "the customer the invoice number and total in your reply, and say the "
    "document will follow."
)


def _not_invoiceable(order_no: str, status: str) -> str:
    """An order that is not in a state anybody can bill for."""
    if status == "CANCELLED":
        return (
            f"Order {order_no} was cancelled, so there is nothing to invoice. Tell "
            "the customer the order is not active and offer to place a new one."
        )
    return (
        f"Order {order_no} has not been confirmed yet ({status}), so it cannot be "
        "invoiced. Confirm the order with the customer first."
    )


def _worth_invoicing(client: erp_client.ErpClient, so: dict) -> bool:
    """Put the order's stock out of the door, unless it already went.

    erp_os refuses to invoice an order that has not shipped, and on a WhatsApp
    order there is nobody in the warehouse to key a delivery note in mid
    conversation. Returns False when the shipment could not be made -- most often
    the branch running out between the order and the invoice.
    """
    if so.get("status") == SHIPPED:
        return True
    try:
        client.ship_sales_order(so)
    except ApiClientError as exc:
        logger.exception("could not ship order %s", so.get("document_no"))
        # A shipment that went out unanswered may well have landed, and the
        # invoice call is what settles it: it succeeds if the stock moved and
        # refuses if it did not. Giving up here would leave that unresolved.
        return bool(exc.may_have_landed)
    return True


def _validated(client: erp_client.ErpClient, invoice: dict) -> dict:
    """The invoice with an LHDN UIN on it, if MyInvois will give us one.

    A DRAFT is still a real invoice and still worth sending; failing the whole
    tool because the tax portal was slow would take a document away from the
    customer over a line of small print.
    """
    if invoice.get("status") != INVOICE_DRAFT:
        return invoice
    try:
        return client.submit_invoice(invoice["id"])
    except (ApiClientError, KeyError):
        logger.exception("could not submit invoice %s to MyInvois", invoice.get("document_no"))
        return invoice


def _deliver(invoice: dict, order_no: str) -> bool:
    """Render the invoice, hand it to Meta, and queue it behind the reply."""
    if not outbox.available():
        # The web demo has no channel to put a document on. Better to say so than
        # to let the bot promise a PDF that was never going anywhere.
        return False
    filename = invoice_pdf.filename_for(invoice)
    try:
        media_id = whatsapp_media.upload_media(invoice_pdf.render(invoice), PDF_MIME, filename)
    except MediaError:
        logger.exception("could not upload the invoice PDF for order %s", order_no)
        return False
    return outbox.add(
        outbox.Attachment(
            media_id=media_id,
            filename=filename,
            caption=f"e-Invoice {invoice.get('document_no', '')} for order {order_no}",
        )
    )


@beta_tool
def erp_generate_einvoice(order_no: str, customer_id: int) -> str:
    """Issue the LHDN e-Invoice for an order and send the PDF to the customer.

    Call this after erp_create_sales_order, once the customer has their order
    number. It ships the order in the ERP, issues the e-Invoice against it,
    submits it to MyInvois for validation, and sends the PDF into this chat. The
    customer receives the document as a file they can open and keep.

    Safe to call again if it fails: nothing is shipped, invoiced or submitted
    twice.

    Args:
        order_no: The order number to bill, exactly as erp_create_sales_order
            returned it, e.g. "SO-2026-0042".
        customer_id: The ERP customer the order belongs to, from
            erp_find_customer. The order is looked up under this customer, so a
            wrong id finds nothing rather than invoicing somebody else's order.
    """
    client = erp_client.client()
    try:
        so = client.sales_order_for_customer(order_no, customer_id)
    except ApiClientError:
        logger.exception("could not look up order %r for customer %s", order_no, customer_id)
        return UNAVAILABLE

    if so is None:
        return NO_SUCH_ORDER
    if so.get("status") not in INVOICEABLE:
        return _not_invoiceable(order_no, str(so.get("status")))

    if not _worth_invoicing(client, so):
        return INVOICE_FAILED

    try:
        invoice = client.invoice_for_sales_order(so["id"])
    except (ApiClientError, KeyError):
        logger.exception("could not issue the invoice for order %s", order_no)
        return INVOICE_FAILED

    invoice = _validated(client, invoice)
    delivered = _deliver(invoice, order_no)

    return _as_json(
        {
            "invoice_no": invoice.get("document_no"),
            "order_no": order_no,
            "status": invoice.get("status"),
            "lhdn_uin": invoice.get("uin"),
            "currency": invoice.get("currency"),
            "total_incl_tax": invoice.get("total_incl_tax"),
            "pdf_sent": delivered,
            **({} if delivered else {"note": PDF_NOT_SENT}),
        }
    )


TOOLS = [
    erp_search_sku,
    erp_get_inventory,
    erp_find_customer,
    erp_create_sales_order,
    erp_generate_einvoice,
]
