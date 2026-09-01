"""Nothing in the tool set can hand the model the `customer_id` the order needs.

`erp_create_sales_order` requires `customer_id: int` and books whatever it is
given -- `erp_os`'s `create_so` does not validate that the customer exists or
that it has anything to do with the conversation. The only customer-lookup tool
in the repository is `crm_lookup_customer`, and it answers out of `crm_os`,
whose contacts are keyed by UUID:

    id = "b47a5f85-6fcc-4ec3-8d54-b77cd3c5ef9f"   (live crm.kelvinpeng.com)

while erp.kelvinpeng.com's customers are integers 1..50 in a completely separate
id space ("Sunrise Hypermart Sdn Bhd" is 1). So at run time the model has no
value it can legitimately pass. It will invent a small integer, and every small
integer is a real, wrong customer -- the order lands on someone else's account
silently, which is exactly the screen the demo asks the salesperson to watch.

The fixture below is the live crm_os response shape, not an invented one.
"""

import json
from unittest.mock import patch

from app.services import api_client
from app.tools import crm, erp

from conftest import LOGIN, response

# One row as crm.kelvinpeng.com really returns it (GET /api/contacts, 2026-09-01).
CRM_CONTACT = {
    "id": "b47a5f85-6fcc-4ec3-8d54-b77cd3c5ef9f",
    "name": "Henry Adams",
    "company": "CleanTech Systems",
    "phone": "+1-303-555-1919",
    "email": "henry@cleantech.test",
    "total_deal_amount": 120000.0,
    "deal_count": 2,
}


def test_the_only_customer_lookup_tool_yields_an_id_the_order_tool_can_use(crm_credentials):
    envelope = {"success": True, "data": {"data": [CRM_CONTACT], "total": 1}}

    with patch.object(api_client.httpx, "post", return_value=response({"data": LOGIN})):
        with patch.object(api_client.httpx, "get", return_value=response(envelope)):
            found = json.loads(crm.crm_lookup_customer("Henry Adams"))

    # `customer_id` is required and typed as an integer, so the model has to get
    # one from a tool -- it cannot ask the ERP, there is no ERP customer tool.
    schema = next(t for t in erp.TOOLS if t.name == "erp_create_sales_order").input_schema
    assert "customer_id" in schema["required"]
    assert schema["properties"]["customer_id"]["type"] == "integer"

    identifier = found[0]["contact_id"]
    assert isinstance(identifier, int), (
        "the only identifier any customer tool hands the model is crm_os's "
        f"contact_id={identifier!r}, which is not an erp_os customer_id -- there "
        "is no tool that returns one, so the model must guess"
    )
