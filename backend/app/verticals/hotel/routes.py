"""The resort's back office, over HTTP.

Under `/api/` and behind the console's token, header only, for the reasons
`verticals/realestate/routes.py` gives: `/api/` is proxied by prefix, so a new
path cannot be silently answered by the SPA, and the list holds guests' names
and phone numbers.

Read-only (user decision, 2026-09-17). Bookings are made and changed by the
model's tools; there is nothing here for a person to press.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.console import require_console_write
from app.verticals.db import StoreUnavailable
from app.verticals.hotel import models

router = APIRouter(
    prefix="/api/verticals/hotel",
    dependencies=[Depends(require_console_write)],
)


@router.get("/bookings", response_model=list[models.Booking])
def read_bookings(limit: int = Query(default=models.DEFAULT_LIMIT, ge=1)) -> list[models.Booking]:
    """Every booking, newest first."""
    try:
        return models.bookings(limit)
    except StoreUnavailable as failure:
        # 503 rather than an empty list: "no bookings yet" and "the database is
        # down" must not look the same on a screen in front of a client.
        raise HTTPException(
            status_code=503, detail="The hotel back office is unavailable"
        ) from failure
