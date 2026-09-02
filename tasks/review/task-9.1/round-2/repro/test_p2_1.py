"""A lead is filed against whichever contact shares the caller's last 8 digits.

`app.services.phone` compares the tail of a number so that "+60 17-394 8123",
"017-3948123" and "60173948123" resolve to one person. Task 8 used that for a
read -- `crm_lookup_customer`, where a wrong hit is visible in the answer and
costs nothing. Task 9.1 makes the same comparison decide **where a write goes**:
`_card` takes the first tail match and posts the new opportunity against that
contact's id.

Eight digits is not a country code apart. A Malaysian landline "03-8555 1515"
and the US number "+1-858-555-1515" -- which is a real row in this demo CRM,
David Park of MedTech Innovations, the contact task 8's own acceptance notes
were written against -- end in the same eight digits. The lead, the card and the
WhatsApp note all land on David Park's record, and the salesperson reads an
enquiry from somebody who was never his customer.

Any tightening of the rule turns this green: comparing the full digit string,
normalising the country code, or refusing to write when the match is not
conclusive. The assertion is only that a stranger's record is not written to.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

from app.services import crm_client
from app.tools import crm

# A seeded row in crm.kelvinpeng.com, phone as it is stored there.
DAVID = {
    "id": "c-1",
    "name": "David Park",
    "company": "MedTech Innovations",
    "phone": "+1-858-555-1515",
    "total_deal_amount": 390000.0,
    "deal_count": 1,
}

# Shah Alam, and eight digits of it are David Park's.
CALLER = "03-8555 1515"

NEW_CONTACT = {"id": "c-9", "name": "Ahmad Faizal", "phone": CALLER}
NEW_DEAL = {"id": "d-9", "title": "t", "amount": 986.70, "status": "lead"}


class FakeCrm:
    def __init__(self, rows):
        self.rows = rows
        self.posts = []

    def get(self, path, params=None):
        if path == "/api/contacts":
            return {"data": self.rows}
        if path == "/api/deals":
            return [NEW_DEAL]
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path, json=None):
        self.posts.append((path, json or {}))
        if path == "/api/contacts":
            return NEW_CONTACT
        if path == "/api/deals":
            return NEW_DEAL
        if path.endswith("/activities"):
            return {"id": "a-1"}
        raise AssertionError(f"unexpected POST {path}")


@contextmanager
def fake_crm(rows):
    fake = FakeCrm(rows)
    crm_client.reset()
    with patch.object(crm_client.CrmClient, "get", side_effect=fake.get):
        with patch.object(crm_client.CrmClient, "post", side_effect=fake.post):
            yield fake
    crm_client.reset()


def test_a_lead_is_not_filed_against_a_stranger_who_shares_eight_digits():
    with fake_crm([DAVID]) as fake:
        payload = json.loads(
            crm.crm_create_lead(
                "Ahmad Faizal", CALLER, "2 units Sony WF-C710N earbuds, COD to Cheras", 986.70
            )
        )

    written_to_david = [
        (path, body)
        for path, body in fake.posts
        if body.get("contact_id") == DAVID["id"] or path == f"/api/deals/{DAVID['id']}/activities"
    ]
    assert written_to_david == [], (
        "Ahmad Faizal's enquiry was written onto David Park's record: "
        f"{written_to_david}"
    )
    assert payload["contact_id"] != DAVID["id"]
