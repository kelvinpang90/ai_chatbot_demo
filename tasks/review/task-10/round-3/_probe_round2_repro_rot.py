"""Read-only probe: if the truncation regressed, what does round 2's committed
repro actually report? It references invoice_pdf.DESCRIPTION_CHARS in its
assertion message, and this commit deleted that constant."""
import importlib.util
from unittest.mock import patch

from app.services import invoice_pdf

print("DESCRIPTION_CHARS still on the module?", hasattr(invoice_pdf, "DESCRIPTION_CHARS"))

spec = importlib.util.spec_from_file_location(
    "round2_repro", "/round2/test_p2_1_the_invoice_names_a_different_product.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Put the round-2 bug back, exactly as it was: cut the name to fit the column.
with patch.object(invoice_pdf, "_description_rows", lambda d: [d[:38]]):
    try:
        mod.test_the_customers_copy_names_the_product_the_erp_named(
            "Farm Fresh Chocolate Flavoured Milk 200ml"
        )
    except Exception as exc:  # noqa: BLE001 -- the type is the whole point
        print("regression reported as:", type(exc).__name__, "--", exc)
    else:
        print("regression NOT detected at all")
