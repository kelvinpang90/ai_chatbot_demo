from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TypedDict

from anthropic import beta_tool

from app.services import erp_client, invoice_pdf, outbox, whatsapp, whatsapp_media
from app.services import phone as phone_service
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
ACCOUNT_FAILED = (
    "The account could not be opened in the ERP system. Nothing was created -- "
    "tell the customer a colleague will set them up and follow up shortly."
)
# Same reasoning as ORDER_UNKNOWN: a write whose answer never came back may well
# have landed, and a second attempt would open a duplicate account under a
# second code, which is worse than waiting.
ACCOUNT_UNKNOWN = (
    "The ERP system stopped responding while the account was being opened, so it "
    "is NOT known whether it exists. Do not try again. Tell the customer their "
    "account is being set up and a colleague will confirm shortly."
)
NEEDS_A_PHONE_NUMBER = (
    "An ERP account needs a phone number, and this conversation has not given "
    "one. Ask the customer for the number the account should be under."
)


# An address is acted on: somebody drives to it. Cutting one to fit would produce
# a real-looking address that is not where the customer lives, and unlike the
# invoice PDF -- which is drawn long after anyone can be asked -- the person who
# wrote this one is still in the conversation. So ask them.
ADDRESS_TOO_LONG = (
    "That delivery address is too long to record, so nothing was ordered. Ask "
    "the customer for a shorter version -- street, city, postcode -- and place "
    "the order again. Do not shorten it yourself."
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


def _as_json(payload: list | dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _prices(sku: dict) -> dict:
    """Both tax bases, each under a name that says which it is.

    Quoting one number was the bug: the ERP prices a line excluding tax and
    totals the order including it, so a bot that read out `unit_price_excl_tax`
    promised RM 299.00 and then sent an invoice for RM 328.90 -- on the very
    screen that exists to prove the back office is real. The model cannot pick
    the right number unless it is told which is which, so it gets both.
    """
    return {
        "unit_price_excl_tax": sku.get("unit_price_excl_tax"),
        "unit_price_incl_tax": sku.get("unit_price_incl_tax"),
    }


# The row id a tapped product comes back on, and the words around the list. The
# id is the whole contract with `_resolve_product_choice` in the webhook: it is
# what turns a tap into the order the customer would otherwise have to type out.
PRODUCT_ROW_PREFIX = "sku:"
PRODUCT_LIST_BUTTON = "View products"
PRODUCT_LIST_SECTION = "Products"
PRODUCT_LIST_BODY = "Tap the one you want and I'll take it from there."

# How many products one search brings back. The ERP's own default is five, which
# is the right size for most of what it is asked, but a search is now the thing
# that fills a tappable list -- so it asks for as many as that list can carry.
# The seed catalogue has exactly five fans, which is to say the old default was
# one new fan away from silently hiding one on the demo screen.
PRODUCT_SEARCH_LIMIT = whatsapp.MAX_LIST_ROWS


def _stock_by_sku(keyword: str) -> dict[int, float]:
    """How many of each matching product can actually be sold, across branches.

    A second call to the ERP, for a line of text on a list nobody has tapped
    yet -- worth it because "2 left" is the difference between a product the
    customer reads about and one they order now. It is also the only number on
    that row they cannot get from the reply.

    Failure is not the caller's problem: the list is still worth sending with
    prices alone, so an unreachable inventory route returns nothing rather than
    taking the products down with it.
    """
    try:
        # The same reach as the search itself: asked for fewer, the products at
        # the bottom of the list would be the only ones with no stock line.
        rows = erp_client.client().branch_inventory(keyword, limit=PRODUCT_SEARCH_LIMIT)
    except ApiClientError:
        logger.warning("no stock line on the product list for %r", keyword, exc_info=True)
        return {}
    return {
        row["sku_id"]: sum(float(cell.get("available") or 0) for cell in row.get("warehouses", []))
        for row in rows
        if row.get("sku_id") is not None
    }


def _row_title(sku: dict) -> str:
    """What to call the product on its row. Empty if it cannot be called anything.

    Meta refuses a row with no title, and refuses the whole message with it, so
    a catalogue entry with neither name nor code takes the other nine products
    down unless it is left out here.
    """
    return str(sku.get("name") or sku.get("code") or "").strip()


def _row_description(sku: dict, available: float | None) -> str:
    """The second line of a product row: what it costs and whether it is there.

    The tax-inclusive price, the same one the tool tells the model to quote --
    a row that says RM 89.00 next to a reply that says RM 94.34 is the sort of
    thing the customer notices on the screen the demo is trying to sell.
    """
    price = " ".join(
        str(part) for part in (sku.get("currency"), sku.get("unit_price_incl_tax")) if part
    )
    if available is None:
        return price
    if available <= 0:
        return f"{price} · out of stock" if price else "out of stock"
    return f"{price} · {available:g} in stock" if price else f"{available:g} in stock"


def _offer_products(keyword: str, matches: erp_client.SkuMatches) -> None:
    """Put the matches behind the reply as rows the customer can tap.

    Deliberately not part of what the tool returns: the model gets the same JSON
    it always did and writes its own answer, and the list rides out behind that
    answer through the outbox. Which means the model cannot forget to offer it,
    and cannot describe it wrongly either.

    Nothing is queued for a single match -- a one-row list is a worse way of
    saying "we have it" than the sentence the model is already writing -- or on
    the web demo, which has no channel to put an interactive message on.
    """
    orderable = [sku for sku in matches.items if sku.get("id") is not None and _row_title(sku)]
    if len(orderable) < 2 or not outbox.available():
        return

    stock = _stock_by_sku(keyword)
    shown = orderable[: whatsapp.MAX_LIST_ROWS]
    rows = [
        whatsapp.list_row(
            f"{PRODUCT_ROW_PREFIX}{sku['id']}",
            _row_title(sku),
            _row_description(sku, stock.get(sku["id"])),
        )
        for sku in shown
    ]
    body = PRODUCT_LIST_BODY
    if matches.total > len(shown):
        # The ERP's count, not the size of the page it sent us: the customer is
        # owed the difference between "we stock these ten" and "here are ten of
        # fourteen", and only one of those is true.
        body = (
            f"Showing {len(shown)} of {matches.total} matches -- tap one to order it, "
            "or tell me the brand or category and I'll narrow it down."
        )
    outbox.add(
        outbox.Choices(
            body=body,
            button=PRODUCT_LIST_BUTTON,
            section_title=PRODUCT_LIST_SECTION,
            rows=rows,
        )
    )


@beta_tool
def erp_search_sku(keyword: str) -> str:
    """Search the ERP product catalogue by name or product code.

    Use this to find a product the customer mentions before quoting a price or
    checking stock. Returns the product code, name and unit price.

    Quote `unit_price_incl_tax`. That is the number the order total and the
    e-Invoice will carry, so quoting the other one means the bill arrives higher
    than the price the customer agreed to.

    `total_matches` is how many products matched in the whole catalogue, and
    `products` is only the first page of them. When it is the larger number, say
    so and offer to narrow the search -- never present the page as the full
    range, and never tell the customer a product does not exist on the strength
    of one page.

    Args:
        keyword: Part of a product name or code, e.g. "earbuds" or "SKU-00012".
    """
    try:
        matches = erp_client.client().search_skus(keyword, limit=PRODUCT_SEARCH_LIMIT)
    except ApiClientError:
        logger.exception("erp_search_sku failed for %r", keyword)
        return UNAVAILABLE

    if not matches.items:
        return NOT_FOUND

    _offer_products(keyword, matches)

    # The catalogue row carries ~30 columns; the model needs the handful a customer
    # would ask about, and the console screen has to stay readable.
    return _as_json(
        {
            "total_matches": matches.total,
            "products": [
                {
                    "sku_id": sku.get("id"),
                    "code": sku.get("code"),
                    "name": sku.get("name"),
                    "name_zh": sku.get("name_zh"),
                    **_prices(sku),
                    "currency": sku.get("currency"),
                }
                for sku in matches.items
            ],
        }
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


def _customer_code(digits: str) -> str:
    """A code that carries the number but is not only the number.

    The number alone would be the obvious choice, and it was, until the cleanup
    in task 34 turned it into a trap. erp_os deletes a customer by marking it
    deleted, and its code-uniqueness check deliberately counts deleted rows
    "to prevent reuse" (`repositories/customer.py:15`). So a demo number whose
    account has been cleaned up could never open one again -- and the demo
    number is the same one every time.

    The stamp keeps that from happening. What stops one customer holding two
    accounts is not this string but the lookup the tool does first, which is the
    honest place for that rule anyway: it asks whether this person has an
    account, rather than whether this exact code was ever issued.
    """
    stamp = datetime.now(erp_client.MALAYSIA_TIME).strftime("%y%m%d%H%M")
    return f"{erp_client.CUSTOMER_CODE_PREFIX}{digits}-{stamp}"


def _customer_summary(customer: dict) -> dict:
    return {
        "customer_id": customer.get("id"),
        "code": customer.get("code"),
        "name": customer.get("name"),
        "phone": customer.get("phone"),
        "currency": customer.get("currency"),
    }


@beta_tool
def erp_create_customer(
    name: str,
    phone: str,
    company: str = "",
    tin: str = "",
    address: str = "",
    city: str = "",
    postcode: str = "",
) -> str:
    """Open an ERP trade account for a customer who does not have one yet.

    Use this when erp_find_customer finds nobody and the customer wants to place
    an order rather than leave an enquiry. It returns a customer_id that
    erp_create_sales_order and erp_generate_einvoice accept, so the order and the
    e-Invoice can be completed in this conversation instead of waiting on a
    salesperson.

    Confirm the details with the customer before calling: this creates a real
    account a salesperson will work from. Ask for a delivery address if you do
    not have one. If they gave a company name, ask for their TIN as well --
    Malaysian e-Invoicing requires a valid TIN on a business invoice, and an
    account opened without one produces an invoice LHDN flags.

    Safe to call again: an account already on file is returned rather than
    duplicated.

    Args:
        name: The person's name.
        phone: Their phone number, in any format.
        company: Their company name, if they are buying as a business. Leave
            empty for an individual.
        tin: Their LHDN tax identification number, if they gave one.
        address: The delivery address, street and unit.
        city: The city or town.
        postcode: The postcode.
    """
    digits = phone_service.digits(phone)
    if not digits:
        return NEEDS_A_PHONE_NUMBER

    client = erp_client.client()
    try:
        # Not merely idempotence: somebody who already has an account must not be
        # given a second one, which would split their orders across two records
        # and leave a salesperson looking at half a history.
        existing = client.find_customers(phone)
        if existing:
            return _as_json({"already_had_an_account": True, **_customer_summary(existing[0])})

        customer = client.create_customer(
            code=_customer_code(digits),
            name=company or name,
            phone=phone,
            contact_person=name if company else None,
            is_business=bool(company),
            tin=tin or None,
            address_line1=address or None,
            city=city or None,
            postcode=postcode or None,
        )
    except ApiClientError as exc:
        logger.exception("erp_create_customer failed for %r", phone)
        return ACCOUNT_UNKNOWN if exc.may_have_landed else ACCOUNT_FAILED

    return _as_json({"created": True, **_customer_summary(customer)})


NO_ORDERS = "This customer has no orders in the ERP system."


@beta_tool
def erp_list_orders(customer_id: int) -> str:
    """List a customer's own orders, newest first, and where each one has got to.

    Use this whenever the customer asks about something they already ordered --
    "where is my order", "has it shipped yet", "what did I order last time". The
    status is the ERP's own word for it: CONFIRMED means the stock is set aside,
    PARTIAL_SHIPPED and FULLY_SHIPPED mean it has left the warehouse, INVOICED
    and PAID mean it has been billed.

    The customer_id must come from erp_find_customer. Never guess one: every
    integer is somebody's real account, so a guessed id reads a stranger's order
    history out loud in this chat.

    Args:
        customer_id: The ERP customer whose orders to list, as returned by
            erp_find_customer.
    """
    try:
        orders = erp_client.client().recent_orders(customer_id)
    except ApiClientError:
        logger.exception("erp_list_orders failed for customer %s", customer_id)
        return UNAVAILABLE

    if not orders:
        return NO_ORDERS

    return _as_json(
        [
            {
                "order_no": order.get("document_no"),
                "status": order.get("status"),
                "ordered_on": order.get("business_date"),
                "currency": order.get("currency"),
                "total_incl_tax": order.get("total_incl_tax"),
            }
            for order in orders
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
    shipping_address: str = "",
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
        shipping_address: Where the goods are to be delivered, in the customer's
            own words, if they gave one in this conversation. Pass it whenever
            they did -- otherwise the order carries no address and nobody knows
            where it goes. Never invent one and never reuse an address from
            another conversation; leave it empty if they did not say.
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

    address = str(shipping_address or "").strip()
    if len(address) > erp_client.MAX_SHIPPING_ADDRESS_CHARS:
        logger.warning("erp_create_sales_order got a %d character address", len(address))
        return ADDRESS_TOO_LONG

    client = erp_client.client()
    try:
        order = client.create_sales_order(
            customer_id=customer_id,
            lines=lines,
            warehouse_id=warehouse_id,
            shipping_address=address,
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
            # What erp_os stored, not what we sent it. Reading back our own
            # argument would report an address recorded whether or not it was.
            "shipping_address": order.get("shipping_address"),
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


# The statuses a first invoice can be raised from. erp_os also has INVOICED and
# PAID, and those are deliberately absent: an order in one of them has an invoice
# already, which is found before this tuple is consulted.
INVOICEABLE = ("CONFIRMED", "PARTIAL_SHIPPED", "FULLY_SHIPPED")
SHIPPED = "FULLY_SHIPPED"
INVOICE_DRAFT = "DRAFT"

PDF_MIME = "application/pdf"

# An invoice in one of these is not a bill any more: LHDN threw it out, or
# somebody in the office withdrew it. Sending one as the customer's copy would be
# handing them a document the ERP no longer stands behind.
VOID_INVOICE = ("REJECTED", "CANCELLED")

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


def _void_invoice(order_no: str, status: str) -> str:
    """An invoice that exists and is not a bill."""
    return (
        f"The invoice for order {order_no} was {status.lower()} and is no longer "
        "valid, so it must not be sent. Do not raise a new one -- tell the "
        "customer a colleague will sort their invoice out and call them back."
    )


def _not_invoiceable(order_no: str, status: str) -> str:
    """An order that is not in a state anybody can bill for.

    Only reached with no invoice already on file, which is what rules out the
    reading that would otherwise be tempting here: an order marked INVOICED whose
    invoice cannot be found is not an order to bill again.
    """
    if status == "CANCELLED":
        return (
            f"Order {order_no} was cancelled, so there is nothing to invoice. Tell "
            "the customer the order is not active and offer to place a new one."
        )
    if status == "DRAFT":
        return (
            f"Order {order_no} has not been confirmed yet, so it cannot be "
            "invoiced. Confirm the order with the customer first."
        )
    return (
        f"Order {order_no} is marked {status} but no invoice could be found for "
        "it. Do not raise a new one -- tell the customer a colleague will send "
        "them their invoice."
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
        order = client.sales_order_for_customer(order_no, customer_id)
        if order is None:
            return NO_SUCH_ORDER
        # From here on the ERP's spelling of the number, not the model's: it is
        # what the customer sees on the document and quotes back on the phone.
        order_no = order.get("document_no") or order_no
        # Asked before a thing is shipped: an order billed once is not billed
        # again, whether that was a minute ago on a call that failed on its way
        # out or six months ago by somebody in the office.
        invoice = client.invoice_for_order(order["id"])
    except (ApiClientError, KeyError):
        logger.exception("could not look up order %r for customer %s", order_no, customer_id)
        return UNAVAILABLE

    if invoice is not None and invoice.get("status") in VOID_INVOICE:
        return _void_invoice(order_no, str(invoice.get("status")))

    if invoice is None:
        if order.get("status") not in INVOICEABLE:
            return _not_invoiceable(order_no, str(order.get("status")))
        if not _worth_invoicing(client, order):
            return INVOICE_FAILED
        try:
            invoice = client.invoice_for_sales_order(order["id"])
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


# -- returns (task 16) ---------------------------------------------------------
#
# The last two steps of scene 2a: the customer photographs something that came
# back broken, and the bot has to find which of their orders it was on and raise
# the refund note against it. Both are harder than they read, for the same
# reason -- erp_os indexes neither orders nor invoices by product.

# How many of the customer's orders a returns enquiry opens. The ERP cannot
# search orders by product (`repositories/sales_order.py:43-83` filters on
# document number and remarks, never on the lines), so every candidate order is
# fetched and read here. One HTTP call each is what puts a ceiling on this
# number, not taste.
ORDERS_SEARCHED_FOR_SKU = 10
# Enough to ask "which of these?" and stop. Somebody who has bought the same
# thing five times is asking about a recent one.
MAX_SKU_ORDER_MATCHES = 3
# A one-character product name matches most catalogues. Below this the answer
# would be "your first order", dressed up as a search result.
MIN_SKU_QUERY_CHARS = 2

NO_ORDER_WITH_THAT_SKU = (
    "None of this customer's recent orders contain that product. Only their "
    "most recent orders were searched, so check the product name with them, or "
    "ask roughly when they bought it and tell them a colleague will dig further "
    "back. Do not tell them they never bought it."
)
NO_SUCH_ORDER_TO_CREDIT = (
    "No order with that number belongs to this customer, so nothing was "
    "refunded. Use the order number erp_find_order_by_sku returned and the "
    "customer_id from erp_find_customer -- do not guess either."
)
# Deliberately not the pair the order tool carries. A refund that may or may not
# have been raised is the one case where trying again is the wrong instinct:
# erp_os will refuse a second credit for goods already credited, and a model
# that "helpfully" retries with a smaller quantity would get one through.
CREDIT_UNKNOWN = (
    "The refund note may or may not have been raised -- the ERP did not answer. "
    "Do not try again. Tell the customer their return is recorded and a "
    "colleague will confirm the refund today."
)
CREDIT_FAILED = (
    "The refund note could not be raised. One reason this happens is that those "
    "goods have already been credited. Do not retry with a different quantity "
    "to get it through -- tell the customer a colleague will check the return "
    "and come back to them."
)
BAD_RETURN_QUANTITY = (
    "That is more of the item than the customer was invoiced for, so no refund "
    "note was raised. Check how many are actually coming back and call this "
    "again with that number."
)


def _matches_sku(line: dict, wanted: str) -> bool:
    """Is this order or invoice line the product the customer means?

    Two spellings arrive here from the model and both are honest: the code it
    read off `erp_search_sku` ("SKU-ELE-0001"), and the words the customer used
    ("sony earbuds"). The code is matched whole, because a code is either this
    product or somebody else's. The name is matched on every word being present,
    which finds "Sony WF-C710N Wireless Earbuds" from either spelling without
    also matching every Sony product in the order once more was said.
    """
    query = " ".join(str(wanted or "").lower().split())
    if len(query) < MIN_SKU_QUERY_CHARS:
        return False
    if query == str(line.get("sku_code") or "").strip().lower():
        return True
    name = str(line.get("sku_name") or "").lower()
    return all(word in name for word in query.split())


def _nothing_billed(order_no: str) -> str:
    return (
        f"Order {order_no} has not been invoiced, so there is nothing to credit "
        "against it. Tell the customer the return is noted and a colleague will "
        "sort the refund out -- do not quote them a refund amount."
    )


def _not_creditable(order_no: str, invoice_no: str, status: str) -> str:
    """A bill that exists and cannot be refunded against.

    erp_os credits VALIDATED and FINAL invoices only
    (`services/credit_note.py:128-302`), which splits into two quite different
    things to tell a customer: one is a document still on its way through LHDN,
    the other is not a bill at all.
    """
    if status in VOID_INVOICE:
        return (
            f"Invoice {invoice_no} for order {order_no} was {status.lower()} and "
            "is not a valid bill, so nothing can be credited against it. Do not "
            "raise anything -- tell the customer a colleague will sort this out "
            "and call them back."
        )
    return (
        f"Invoice {invoice_no} for order {order_no} is still {status} and cannot "
        "be credited until LHDN has validated it. Tell the customer their return "
        "is accepted and the refund note follows once the invoice clears, which "
        "is usually the same day."
    )


def _no_warehouse_to_return_to(order_no: str, invoice_no: str) -> str:
    """A bill in a state no return can be booked against.

    erp_os will not credit an invoice with no warehouse on it, because a return
    puts stock back somewhere (`services/credit_note.py:128-302`). Found on the
    live demo ERP on 2026-09-11: every seeded invoice is like this, and only the
    ones this bot raised itself through erp_generate_einvoice carry a branch. It
    reads as an ERP quirk and it is one -- but without this check it reaches the
    customer as "that has already been refunded", which is a different and
    untrue thing to be told.
    """
    return (
        f"Invoice {invoice_no} for order {order_no} has no branch recorded on "
        "it, so the ERP cannot book the goods back in and no refund note can be "
        "raised against it. Tell the customer the return is accepted and a "
        "colleague will process the refund by hand."
    )


def _not_on_the_invoice(order_no: str, sku: str) -> str:
    return (
        f"Order {order_no} was not invoiced for '{sku}', so there is nothing to "
        "credit. Check which product the customer means, or which order it was "
        "on, with erp_find_order_by_sku."
    )


@beta_tool
def erp_find_order_by_sku(customer_id: int, sku: str) -> str:
    """Find which of this customer's own orders contained a given product.

    Use this when a customer wants to return, replace or ask about something
    they already bought and you need the order it came on -- "this arrived
    cracked", "when did I buy this one". Pass the product code from
    erp_search_sku where you have one, otherwise the product name in the
    customer's own words.

    Only this customer's most recent orders are searched, newest first. Nothing
    found means nothing found recently, which is not the same as never bought --
    say so that way.

    The customer_id must come from erp_find_customer. Never guess one: every
    integer is somebody's real account, and a guessed id reads a stranger's
    purchase history out loud in this chat.

    Args:
        customer_id: The ERP customer whose orders to search, as returned by
            erp_find_customer.
        sku: The product to look for -- the code from erp_search_sku, e.g.
            "SKU-ELE-0001", or the name the customer used, e.g. "sony earbuds".
    """
    client = erp_client.client()
    try:
        orders = client.recent_orders(customer_id, limit=ORDERS_SEARCHED_FOR_SKU)
    except ApiClientError:
        logger.exception("erp_find_order_by_sku failed for customer %s", customer_id)
        return UNAVAILABLE

    if not orders:
        return NO_ORDERS

    matches = []
    for order in orders:
        try:
            detail = client.sales_order(order["id"])
        except (ApiClientError, KeyError):
            # Not skipped. A half-read search reported as "no such order" tells a
            # customer they never bought the thing in their hand, which is the
            # one answer this tool must never give by accident.
            logger.exception("could not read order %s while searching for a sku", order.get("id"))
            return UNAVAILABLE

        line = next((row for row in detail.get("lines", []) if _matches_sku(row, sku)), None)
        if line is None:
            continue
        matches.append(
            {
                "order_no": detail.get("document_no"),
                "status": detail.get("status"),
                "ordered_on": detail.get("business_date"),
                "currency": detail.get("currency"),
                "item": {
                    "code": line.get("sku_code"),
                    "name": line.get("sku_name"),
                    "qty": line.get("qty_ordered"),
                    "line_total_incl_tax": line.get("line_total_incl_tax"),
                },
            }
        )
        if len(matches) >= MAX_SKU_ORDER_MATCHES:
            break

    return _as_json(matches) if matches else NO_ORDER_WITH_THAT_SKU


@beta_tool
def erp_create_credit_note(
    order_no: str,
    customer_id: int,
    sku: str,
    reason: str = "",
    quantity: float = 0,
) -> str:
    """Raise the refund note for goods a customer is sending back.

    This writes to the live back office and puts the goods back into stock, so
    only call it once the customer has said what is wrong and what they are
    returning. Find the order with erp_find_order_by_sku first.

    What it creates is the credit note against the invoice -- the document the
    accounts office refunds from. It is not the money arriving in their account,
    so tell the customer their refund has been raised and will be processed,
    never that they have been refunded.

    Only call this once. If it fails, do not call it again with different
    numbers: say a colleague will confirm the refund.

    Args:
        order_no: The order the goods came on, exactly as erp_find_order_by_sku
            returned it, e.g. "SO-2026-0042".
        customer_id: The ERP customer that order belongs to, from
            erp_find_customer. The order is looked up under this customer, so a
            wrong id finds nothing rather than refunding somebody else.
        sku: Which product is coming back -- the code from erp_search_sku or the
            name the customer used. One product per call.
        reason: Why it is coming back, in the customer's own words, e.g.
            "case arrived cracked". It is written onto the refund note, which is
            what the office reads when they look at it. Leave it empty rather
            than inventing a reason they did not give.
        quantity: How many units are coming back. Leave it out to credit the
            whole quantity that was invoiced, which is what a customer returning
            "it" means.
    """
    client = erp_client.client()
    try:
        order = client.sales_order_for_customer(order_no, customer_id)
        if order is None:
            return NO_SUCH_ORDER_TO_CREDIT
        # From here on the ERP's spelling of the number, not the model's.
        order_no = order.get("document_no") or order_no
        invoice = client.invoice_for_order(order["id"])
    except (ApiClientError, KeyError):
        logger.exception("could not look up order %r for customer %s", order_no, customer_id)
        return UNAVAILABLE

    if invoice is None:
        return _nothing_billed(order_no)
    status = str(invoice.get("status"))
    invoice_no = str(invoice.get("document_no"))
    if status not in erp_client.CREDITABLE_INVOICE:
        return _not_creditable(order_no, invoice_no, status)
    if not invoice.get("warehouse_id"):
        return _no_warehouse_to_return_to(order_no, invoice_no)

    line = next((row for row in invoice.get("lines", []) if _matches_sku(row, sku)), None)
    if line is None:
        return _not_on_the_invoice(order_no, sku)

    try:
        invoiced = float(line.get("qty") or 0)
        coming_back = invoiced if float(quantity) <= 0 else float(quantity)
    except (TypeError, ValueError):
        logger.warning("erp_create_credit_note got an unusable quantity: %r", quantity)
        return BAD_RETURN_QUANTITY

    # The ERP has the last word here -- what is left creditable is the invoiced
    # quantity less whatever earlier credit notes already took, which is not
    # visible from this side. This catches the obvious case while the customer
    # is still reading, rather than after a round trip.
    if coming_back <= 0 or coming_back > invoiced:
        return BAD_RETURN_QUANTITY

    try:
        note = client.create_credit_note(
            invoice_id=invoice["id"],
            lines=[(line["id"], coming_back)],
            reason_description=str(reason or "").strip(),
        )
    except (ApiClientError, KeyError) as exc:
        logger.exception("could not credit order %s for customer %s", order_no, customer_id)
        unknown = isinstance(exc, ApiClientError) and exc.may_have_landed
        return CREDIT_UNKNOWN if unknown else CREDIT_FAILED

    return _as_json(
        {
            "credit_note_no": note.get("document_no"),
            "status": note.get("status"),
            "order_no": order_no,
            "invoice_no": invoice.get("document_no"),
            "currency": note.get("currency"),
            "total_incl_tax": note.get("total_incl_tax"),
            "item": {
                "code": line.get("sku_code"),
                "name": line.get("sku_name"),
                "qty_returned": coming_back,
            },
        }
    )


TOOLS = [
    erp_search_sku,
    erp_get_inventory,
    erp_find_customer,
    erp_create_customer,
    erp_list_orders,
    erp_create_sales_order,
    erp_generate_einvoice,
    erp_find_order_by_sku,
    erp_create_credit_note,
]
