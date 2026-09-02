"""What does the model actually see for crm_create_lead?

Task 9 round 2 recorded that `beta_tool` takes only the docstring's first
paragraph as the tool description. This asks the same question of the tool
task 9.1 ships.
"""
import json

from app.tools import crm

for tool in crm.TOOLS:
    print("=" * 70)
    print("NAME:", tool.name)
    print("--- description the model sees ---")
    print(repr(tool.description))
    print("--- input schema ---")
    print(json.dumps(tool.input_schema, indent=2, ensure_ascii=False))

print("=" * 70)
for phrase in (
    "shown real interest",
    "not for a passing question",
    "writes to the live CRM",
    "instead of a duplicate entry",
):
    print(f"{phrase!r:40} in description: "
          f"{phrase in (crm.crm_create_lead.description or '')}")
