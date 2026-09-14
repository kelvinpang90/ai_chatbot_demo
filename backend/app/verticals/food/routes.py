"""The restaurant's back office, over HTTP.

Under `/api/` and behind the console's token, header only, for the reasons
`verticals/realestate/routes.py` gives at length: `/api/` is proxied by prefix
so a new path cannot be silently answered by the SPA, and the list holds names,
phone numbers and home addresses.

Read-only. Orders are placed by the model's tool and move along their own
timeline; there is nothing here for a person to press.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.console import require_console_write
from app.verticals.db import StoreUnavailable
from app.verticals.food import models

router = APIRouter(
    prefix="/api/verticals/food",
    dependencies=[Depends(require_console_write)],
)


@router.get("/orders", response_model=list[models.Order])
def read_orders(limit: int = Query(default=models.DEFAULT_LIMIT, ge=1)) -> list[models.Order]:
    """Every order, newest first, each with the stage it is in right now."""
    try:
        return models.orders(limit)
    except StoreUnavailable as failure:
        # 503 rather than an empty list: "no orders yet" and "the database is
        # down" must not look the same on a screen in front of a client.
        raise HTTPException(
            status_code=503, detail="The restaurant back office is unavailable"
        ) from failure
