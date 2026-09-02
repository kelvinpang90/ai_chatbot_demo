"""Read-only: does the shipped matcher really pick David Park out of the live CRM
for a Malaysian landline? `_card` uses this same call to choose where to write."""
import os

from app.config import settings

settings.crm_email = os.environ["CRM_EMAIL"]
settings.crm_password = os.environ["CRM_PASSWORD"]

from app.services import crm_client  # noqa: E402
from app.tools import crm  # noqa: E402

CALLER = "03-8555 1515"

print("caller:", CALLER)
print("crm_lookup_customer ->", crm.crm_lookup_customer(CALLER))
print()
hit = crm_client.client().lookup_contacts(CALLER, limit=1)
print("what _card would pick as 'somebody already on the books':")
print(" ", [{"id": r["id"], "name": r["name"], "phone": r["phone"]} for r in hit])
