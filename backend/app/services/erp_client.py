from __future__ import annotations

from app.config import settings
from app.services.api_client import JsonApiClient

# A customer asking about stock wants the two or three products they mean, not a
# catalogue page. Keeping the result small also keeps the console readable.
DEFAULT_RESULT_LIMIT = 5


class ErpClient(JsonApiClient):
    """erp_os over its own REST routes.

    Deliberately not straight to MySQL: writes have to go through the business
    logic or the back office fills up with rows the ERP itself considers invalid,
    and reads should see exactly what the screen behind us is showing.
    """

    def __init__(self) -> None:
        super().__init__(
            name="erp",
            base_url=settings.erp_base_url,
            email=settings.erp_email,
            password=settings.erp_password,
        )

    def search_skus(self, keyword: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Products matching a name or code fragment."""
        payload = self.get("/api/skus", params={"search": keyword, "page_size": limit})
        return payload.get("items", [])

    def branch_inventory(self, sku_query: str, *, limit: int = DEFAULT_RESULT_LIMIT) -> list[dict]:
        """Stock for the matching SKUs, one row per SKU, broken down by warehouse.

        `/api/inventory/stocks` would be the more obvious route but it demands a
        warehouse_id, and a customer asking "got stock or not" means across the
        whole shop. The matrix answers that in one call.
        """
        payload = self.get(
            "/api/inventory/branch-matrix",
            params={"sku_query": sku_query, "page_size": limit},
        )
        return payload.get("rows", [])


_client: ErpClient | None = None


def client() -> ErpClient:
    """One process-wide client, so the cached token is actually shared."""
    global _client
    if _client is None:
        _client = ErpClient()
    return _client


def reset() -> None:
    """Drop the cached client. For tests."""
    global _client
    _client = None
