"""The sales pipeline a seeded conversation leaves behind (task 39.4).

A retail customer who asks about a product and then wants some, and every
property viewing, ends with a lead on the CRM board -- because that is what the
live bots do at exactly that point: retail's persona says an enquiry from
somebody the ERP does not know goes to `crm_create_lead`, and realestate's says
to record the enquiry once a viewing is confirmed. A console conversation
showing that card while the CRM holds nothing is a demo that falls over the
moment somebody opens the board beside it.

Written through `crm_client` rather than by calling `crm_create_lead`, for the
same reason the food order is filed through its model function (task 39.2): the
tool marks what it writes `[DEMO]`, and `app.tasks.cleanup` deletes every
`[DEMO]` row between demos -- which is precisely what the seed's rows must
survive. They carry `SEED_MARK` instead, and the card the console shows is
rebuilt field for field from what the tool would have answered.

So there are two marks and two jobs, and neither can reach the other's rows:
`cleanup` deletes `[DEMO]`, this deletes `[DEMO-SEED]`.

**Nothing here is dated.** crm_os stamps `created_at` itself and neither create
route accepts a date, so unlike every other thing the seed files -- audit rows,
orders, bookings, tickets, viewings, all backdated across four weeks -- the
cards all carry the moment the seed ran. The board shows that the leads arrived,
not that they arrived over weeks.
"""

from __future__ import annotations

import re

from app.services import crm_client
from app.tools import crm as crm_tools

# Read by the salesperson who opens the record. It says what the row is, because
# a seeded contact that reads like a real enquiry is worse than no contact.
NOTES = crm_client.marked(
    "Seeded for the director's console demo. Not a real enquiry.", crm_client.SEED_MARK
)


def phone_for(key_id: str) -> str:
    """A number for a seeded customer that reaches nobody.

    A blank one is not an option: `crm_create_lead` refuses a lead with no
    number to ring back (`crm._usable`), so a card with an empty phone column is
    one the live system could not have produced -- and a seeded card has to be
    the card the live system makes.

    `01X` user numbers are not handed out beginning `000`, so no handset is on
    this block, and the seed key's own digits ride in the last four so a row on
    the board can be traced back to the conversation that left it. What cannot
    be promised is that the eight-digit tail both back offices match on is
    unique -- some landline block could end the same way. The cost if one did is
    one lookup inside a demo CRM naming the wrong person, and the batch is
    replaced every night.
    """
    return f"+60 12-000 {int(re.sub(r'[^0-9]', '', key_id) or 0):04d}"


class Leads:
    """Files each lead and hands back what the tool would have said. Faked in tests."""

    def __init__(self, client: crm_client.CrmClient) -> None:
        self._client = client
        self.filed = 0

    def lead(
        self,
        *,
        name: str,
        phone: str,
        requirement: str,
        amount: float,
        delivery_address: str = "",
    ) -> dict:
        """One contact, the card crm_os makes with it, and the note inside it.

        Nothing here is forgiving. The live tool swallows a failed note and a
        card it cannot find again, because by then the customer has been told
        their enquiry is in; a seed that did the same would report a success and
        leave the console naming a card nobody can open.
        """
        # Marked before it is trimmed, the way `crm._usable` does it: a mark put
        # in front of an already full-length title pushes it over the column.
        title = crm_client.marked(requirement, crm_client.SEED_MARK)[: crm_client.MAX_TITLE_CHARS]
        contact = self._client.create_contact(
            name=name[: crm_client.MAX_NAME_CHARS],
            phone=phone,
            title=title,
            amount=amount,
            notes=NOTES,
        )
        contact_id = contact.get("id")
        deals = self._client.deals_for_contact(contact_id)
        if not deals:
            raise RuntimeError(f"crm_os made no card for seeded contact {contact_id}")
        deal = deals[0]
        # The note is the tool's own, so the salesperson reads the same sentence
        # a real enquiry leaves.
        note = crm_tools._activity_note(
            crm_tools._Lead(
                name=name,
                phone=phone,
                title=title,
                requirement=requirement,
                amount=amount,
                delivery_address=delivery_address,
            )
        )
        self._client.log_activity(deal_id=deal["id"], content=note)
        self.filed += 1
        return {
            "contact_id": contact_id,
            "contact_name": contact.get("name"),
            "deal_id": deal.get("id"),
            "title": deal.get("title"),
            "amount": deal.get("amount"),
            "status": deal.get("status"),
            "activity_logged": True,
        }


def clear(client: crm_client.CrmClient) -> int:
    """Delete every row a previous seed filed, and nothing else.

    Contacts first, each taking its own cards with it by cascade, then whatever
    marked card is still standing. `cleanup` does these two the other way round
    because the rows it deletes are mostly cards filed onto customers who have
    to stay; here every card the seed writes hangs off a contact the seed
    opened, so the second pass finds nothing -- and is kept anyway, because a
    rule that only clears what today's code writes leaves rows behind the day
    that changes.
    """
    deleted = 0
    for contact in client.all_contacts():
        if crm_client.is_marked(contact.get("notes"), crm_client.SEED_MARK):
            client.delete_contact(contact["id"])
            deleted += 1
    for deal in client.all_deals():
        if crm_client.is_marked(deal.get("title"), crm_client.SEED_MARK):
            client.delete_deal(deal["id"])
            deleted += 1
    return deleted
