"""The property agency's back office, over HTTP.

**Mounted under `/api/`, not under `/console/`, and that is a deployment
decision rather than a naming one.** Every path under `/console/` has to be
named a third and fourth time -- in `frontend/nginx.conf` and in
`vite.config.ts` -- or it is answered by the SPA instead of the backend, which
is a failure that only shows up on the deployed site. Task 19.1 shipped a button
that was dead in production for exactly that reason and
`backend/tests/test_console_routing.py` exists because of it. `/api/` is already
proxied by both, by prefix, so these three routes cannot fall into that hole.

They still carry the console's token. The list holds the names and phone numbers
of people who asked to be shown round a house, and it is opened on a laptop
beside the console, so header-only via `require_console_write`: there is no
EventSource here, so nothing needs the weaker query-string form that lands in
the proxy's access log.
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.console import require_console_write
from app.verticals.db import StoreUnavailable
from app.verticals.realestate import models

router = APIRouter(
    prefix="/api/verticals/realestate",
    dependencies=[Depends(require_console_write)],
)


@contextmanager
def _store_up():
    """Turn the store being down into a 503 instead of a 500.

    `StoreUnavailable` is what `verticals/db.py` raises rather than quietly
    writing nothing, and this is the router half of that bargain: the page above
    can then say the back office is unreachable, which is true, instead of
    showing an empty list, which is not.
    """
    try:
        yield
    except StoreUnavailable as failure:
        raise HTTPException(
            status_code=503, detail="The property back office is unavailable"
        ) from failure


@router.get("/listings", response_model=list[models.Listing])
def read_listings() -> list[models.Listing]:
    """What KL Homes Realty has on its books, cheapest first."""
    with _store_up():
        return models.listings()


@router.get("/viewings", response_model=list[models.Viewing])
def read_viewings(limit: int = Query(default=models.DEFAULT_LIMIT, ge=1)) -> list[models.Viewing]:
    """Who asked to see what, newest first. This is the screen."""
    with _store_up():
        return models.viewings(limit)


@router.post("/viewings", response_model=models.Viewing, status_code=201)
def book_viewing(request: models.ViewingRequest) -> models.Viewing:
    """File a viewing request and hand back the row as the back office has it.

    The listing is checked first so that a typo'd id fails here, where whoever
    made it is listening, rather than becoming a row on the screen with a blank
    property beside it during a demo.
    """
    with _store_up():
        if not models.listing_exists(request.listing_id):
            raise HTTPException(status_code=404, detail=f"No listing {request.listing_id}")
        booked = models.get_viewing(models.book_viewing(request))
    if booked is None:
        # Only reachable if something removed the row between writing it and
        # reading it back. Worth saying rather than answering with a half-built
        # object: the caller would be told the booking exists, and it does not.
        raise HTTPException(
            status_code=500, detail="The viewing was written but could not be read back"
        )
    return booked
