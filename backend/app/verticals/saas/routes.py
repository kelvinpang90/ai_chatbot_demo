"""The support desk's back office, over HTTP.

Under `/api/` and behind the console's token, header only, for the reasons
`verticals/realestate/routes.py` gives: `/api/` is proxied by prefix, and the list
holds customers' names, phone numbers and what they reported.

Read-only (user decision, 2026-09-17). Tickets are opened by the model's tool;
there is nothing here for a person to press.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.console import require_console_write
from app.verticals.db import StoreUnavailable
from app.verticals.saas import models

router = APIRouter(
    prefix="/api/verticals/saas",
    dependencies=[Depends(require_console_write)],
)


@router.get("/tickets", response_model=list[models.Ticket])
def read_tickets(limit: int = Query(default=models.DEFAULT_LIMIT, ge=1)) -> list[models.Ticket]:
    """Every ticket, newest first."""
    try:
        return models.tickets(limit)
    except StoreUnavailable as failure:
        # 503 rather than an empty list: "no tickets yet" and "the database is
        # down" must not look the same on a screen in front of a client.
        raise HTTPException(
            status_code=503, detail="The support desk back office is unavailable"
        ) from failure
