"""Does the acceptance command written into todo.md actually work?

    docker run ... -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 \
      python:3.13-slim sh -c "pip install -q -r requirements.txt && python -c \
      \"from app.tools.crm import *; print(crm_create_lead('Ahmad Faizal', ...))\""

Two things to check: (a) is a @beta_tool-decorated name callable like a plain
function, and (b) the command passes no CRM_EMAIL / CRM_PASSWORD, so what does
it print? Nothing here writes -- the second question answers itself before any
byte leaves the process.
"""
from app.tools.crm import *  # noqa: F403  -- verbatim from the documented command
from app.tools import crm

print("type of crm_create_lead:", type(crm_create_lead))  # noqa: F405
print("callable:", callable(crm_create_lead))  # noqa: F405

from app.config import settings  # noqa: E402

print("crm_email as the command leaves it:", repr(settings.crm_email))

out = crm_create_lead("Ahmad Faizal", "+60 12-333 4444",  # noqa: F405
                      "3 units Sony WF-C710N earbuds, COD to Cheras", 986.70)
print("printed by the documented command:")
print("   ", out)
print("is LEAD_FAILED:", out == crm.LEAD_FAILED)
