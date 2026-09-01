"""Round 1's P1 is only half closed: the model can no longer invent a
customer_id, but nothing stops it picking the wrong one out of five.

`erp_find_customer` returns up to five accounts. Every guard-rail written for it
addresses the *empty* case -- "If nothing comes back, say so -- never guess an
id", "do not invent a customer_id" -- and nothing addresses the *ambiguous* case,
which is the one that actually happens. The rows below are what
erp.kelvinpeng.com really returned for `erp_find_customer("Tan")` on 2026-09-01:
two people actually called Tan and three companies that merely contain the
letters. A customer who says "I'm Tan" gets one of the five, chosen by the model,
and the order is booked and CONFIRMED against it -- the same stranger's account
round 1 called a P1, reached by a different door.

A fix can live in either place: say it in what the tool returns, or say it in a
tool description the model always sees. The assertion accepts both.
"""

import json
from unittest.mock import patch

from app.services import api_client, erp_client
from app.tools import erp

from conftest import LOGIN, response

# GET https://erp.kelvinpeng.com/api/customers?search=Tan&page=1&page_size=5,
# live on 2026-09-01, trimmed to the keys the tool reads.
REAL_TAN_MATCHES = [
    {"id": 2, "code": "CUS-002", "name": "Megamart Retail Group Sdn Bhd",
     "phone": "+60 3-2142 2222", "currency": "MYR"},
    {"id": 11, "code": "CUS-011", "name": "Penang Char Koay Teow Co Sdn Bhd",
     "phone": "+60 4-226 2020", "currency": "MYR"},
    {"id": 26, "code": "CUS-026", "name": "Guardian Health & Beauty Sdn Bhd",
     "phone": "+60 3-2382 8877", "currency": "MYR"},
    {"id": 31, "code": "CUS-031", "name": "Tan Ah Kow",
     "phone": "+60 12-345 6789", "currency": "MYR"},
    {"id": 49, "code": "CUS-049", "name": "Tan Hui Ling",
     "phone": "+60 19-678 9012", "currency": "MYR"},
]

# Words a rule about choosing between candidates would have to use one of.
_CHOOSING_CUES = (
    "more than one",
    "several",
    "multiple",
    "which one",
    "which of",
    "ambiguous",
    "confirm which",
    "ask the customer which",
    "do not pick",
    "more than 1",
)


def _tool(name):
    return next(tool for tool in erp.TOOLS if tool.name == name)


def test_five_candidates_come_back_with_no_rule_for_choosing_between_them(erp_credentials):
    erp_client.reset()
    with patch.object(api_client.httpx, "post", return_value=response(LOGIN)):
        with patch.object(
            api_client.httpx, "get", return_value=response({"items": REAL_TAN_MATCHES})
        ):
            answer = erp.erp_find_customer("Tan")

    candidates = json.loads(answer)
    assert len(candidates) == 5, "the live ERP really does answer 'Tan' with five accounts"

    # Where the model could possibly be told what to do with five of them.
    everything_the_model_sees = " ".join(
        [
            answer,
            _tool("erp_find_customer").description,
            _tool("erp_create_sales_order").description,
        ]
    ).lower()

    assert any(cue in everything_the_model_sees for cue in _CHOOSING_CUES), (
        "five real accounts came back and nothing -- not the payload, not either "
        "tool description -- tells the model that picking one is not allowed. "
        "The only rule written is about an empty result:\n  "
        + _tool("erp_find_customer").description.replace("\n", " ")
    )
