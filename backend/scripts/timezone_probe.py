"""What the live ERP and CRM actually put on the wire, and whether their history is UTC.

Read-only. GETs only; nothing is created, updated or deleted.

Two questions the source code cannot answer, and the fix must not be attempted
without both:

1. **What shape is the timestamp on the wire?** The claim is that a naive
   datetime is serialised with no `Z` and no offset, which `new Date()` then
   reads as browser-local. Source says so; this says so from outside.

2. **Is every historical row really UTC?** This is the one that decides whether
   the fix is safe. erp_os writes `created_at` from MySQL `CURRENT_TIMESTAMP`
   (`models/base.py:16`), whose zone is the database server's and is not visible
   from any repository here. So it needs a ruler of known provenance held
   against it.

   The ruler is crm_os. Every order this bot places also opens a deal, seconds
   later, and crm_os writes `created_at` with Python's `datetime.utcnow()`
   (`models/deal.py:36`) -- naive UTC by construction, independent of any
   container or database clock. The deal's title carries the order number, so
   the two rows can be paired across the systems. If a pair is seconds apart,
   the database clock was UTC when that order was written. If the order runs
   ~8h ahead of its own deal, that row was written under a local-time clock, is
   displaying correctly today, and the fix would push it 8 hours late.

   A second, weaker check catches the same thing without a pair: a row written
   under a +08:00 clock reads 8 hours ahead of the instant it happened, so a
   recent one lands in the future. Nothing may be in the future.

Run it the way the tests run:

    docker run --rm -e PYTHONPATH=/repo/backend \
        -v "<repo>:/repo" -v "<main>/backend/.env:/repo/backend/.env:ro" \
        -w /repo/backend python:3.13-slim \
        sh -c "pip install -q -r requirements.txt && python scripts/timezone_probe.py"
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.crm_client import CrmClient
from app.services.erp_client import ErpClient

# A timestamp that says which zone it is in. Either a trailing Z or a +HH:MM.
# Anything else is the bug: `new Date("2026-09-12T08:49:00")` is local time by
# specification, not UTC.
ZONED = re.compile(r"(Z|[+-]\d{2}:\d{2})$")

# A date-only field. These must come out of the fix untouched -- a serializer
# that also stamps `business_date` as "...T00:00:00Z" moves the document date to
# the previous day on any browser west of Greenwich.
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# How a deal names the order it came from, e.g. "(订单 SO-2026-00002, ...)".
ORDER_NO = re.compile(r"SO-\d{4}-\d+", re.IGNORECASE)

HOUR = 3600

# Malaysia is UTC+8 and has no daylight saving, so a row written under a local
# clock sits exactly this far ahead of the instant it happened.
SUSPECT_GAP = 4 * HOUR


def _parse(value):
    """A wire timestamp as an aware UTC datetime, or None if it is not one."""
    if not isinstance(value, str) or DATE_ONLY.match(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive one is the thing under investigation: read it as UTC, which is
    # what the source says it is, so the comparison below is apples to apples.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _shape(label: str, rows: list[dict], fields: list[str]) -> None:
    """Which fields carry a zone and which do not."""
    print(f"\n--- {label}: what is on the wire ---")
    if not rows:
        print("  (no rows came back)")
        return
    sample = rows[0]
    for field in fields:
        value = sample.get(field)
        if value is None:
            print(f"  {field:20s} null")
        elif DATE_ONLY.match(str(value)):
            print(f"  {field:20s} {str(value)!r:26s} date-only, must stay untouched")
        else:
            mark = "HAS a zone" if ZONED.search(str(value)) else "NO zone  <-- the bug"
            print(f"  {field:20s} {str(value)[:24]!r:26s} {mark}")


def _every_field(label: str, rows: list[dict]) -> None:
    """Every field in the payload that looks like a timestamp, not just the ones
    we thought to name. A field nobody listed is exactly how a fix misses one."""
    zoned, naive, dates = set(), set(), set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if not isinstance(value, str):
                continue
            if DATE_ONLY.match(value):
                dates.add(key)
            elif re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", value):
                (zoned if ZONED.search(value) else naive).add(key)
    print(f"\n--- {label}: every timestamp-shaped field found ---")
    print(f"  naive (needs the fix): {sorted(naive) or 'none'}")
    print(f"  already zoned:         {sorted(zoned) or 'none'}")
    print(f"  date-only (hands off): {sorted(dates) or 'none'}")


def _future(label: str, rows: list[dict], fields: list[str]) -> None:
    """Nothing may be in the future. A row written under a +08:00 database clock
    reads 8h ahead of when it happened, so a recent one shows up here."""
    now = datetime.now(timezone.utc)
    ahead = []
    for row in rows:
        for field in fields:
            stamp = _parse(row.get(field))
            # Seeded demo data is dated deliberately into the future; only the
            # created/updated stamps are machine-written and meaningful here.
            if stamp and (stamp - now).total_seconds() > 300:
                ahead.append((row.get("document_no") or row.get("title"), field, row.get(field)))
    print(f"\n--- {label}: anything dated in the future? ---")
    if ahead:
        for doc, field, value in ahead[:20]:
            print(f"  AHEAD {str(doc)[:30]:32s} {field:14s} {value}")
        print(f"  {len(ahead)} in total -- read the note above before concluding")
    else:
        print("  Nothing. No row reads as written under a +08:00 clock.")


def _span(label: str, rows: list[dict], field: str) -> None:
    """How far back the history being judged actually goes."""
    stamps = sorted(s for s in (_parse(r.get(field)) for r in rows) if s)
    print(f"\n--- {label}: span of {field} ---")
    if not stamps:
        print("  (nothing to measure)")
        return
    now = datetime.now(timezone.utc)
    print(f"  oldest  {stamps[0].isoformat()}")
    print(f"  newest  {stamps[-1].isoformat()}")
    print(f"  utc now {now.isoformat()}")
    print(f"  newest is {(now - stamps[-1]).total_seconds() / HOUR:+.2f}h old, read as UTC")


def _detail_ruler(erp, orders: list[dict], sample: int = 25) -> None:
    """The decisive one: `created_at` against `confirmed_at` on the same row.

    `created_at` is MySQL's `CURRENT_TIMESTAMP` (`models/base.py:16`) and is the
    value of unknown provenance. `confirmed_at` is Python's `datetime.now(UTC)`
    (`services/sales.py:371`) on the same row, minutes apart at most. The list
    endpoint drops `confirmed_at`; the detail endpoint carries it, so this costs
    one request per order and is worth it -- it is the only check that reads the
    database clock directly rather than inferring it.

    Sampled across the whole span, oldest included, not just the newest page.
    """
    # Seeded rows are useless as a ruler and actively misleading: the seeder
    # backdates `confirmed_at` to a fabricated business day at exactly 00:00:00,
    # so every one of them reads as a multi-week "gap". Only rows written by a
    # running system carry a `confirmed_at` that is a real Python UTC stamp.
    real = [row for row in orders if not str(row.get("document_no", "")).upper().startswith("SO-SEED")]
    print(f"\n  {len(orders) - len(real)} seeded rows excluded; "
          f"{len(real)} genuinely written rows remain.")
    ordered = sorted(real, key=lambda row: str(row.get("created_at") or ""))
    if len(ordered) > sample:
        step = len(ordered) / sample
        ordered = [ordered[int(i * step)] for i in range(sample)]

    print("\n--- THE RULER: created_at (MySQL clock) vs confirmed_at (Python UTC) ---")
    print(f"  {len(ordered)} orders sampled evenly across the whole span.")
    checked = suspect = 0
    worst = 0.0
    for row in ordered:
        try:
            detail = erp.get(f"/api/sales-orders/{row['id']}")
        except Exception as exc:  # a row we cannot read proves nothing either way
            print(f"  SKIP {row.get('document_no')}: {str(exc)[:80]}")
            continue
        created, confirmed = _parse(detail.get("created_at")), _parse(detail.get("confirmed_at"))
        if created is None or confirmed is None:
            continue
        # Belt and braces: a stamp landing on exact midnight was written by a
        # seeder, not by a clock.
        if (confirmed.hour, confirmed.minute, confirmed.second) == (0, 0, 0):
            print(f"  SEEDED {detail.get('document_no')}: confirmed_at is midnight, not a real stamp")
            continue
        checked += 1
        gap = (created - confirmed).total_seconds()
        worst = max(worst, abs(gap))
        if abs(gap) > SUSPECT_GAP:
            suspect += 1
            print(f"  SUSPECT {detail.get('document_no'):18s} created {detail.get('created_at')} "
                  f"confirmed {detail.get('confirmed_at')} gap {gap / HOUR:+.2f}h")
    print(f"  checked {checked}, suspect {suspect}, worst gap {worst:.0f}s")
    if checked == 0:
        print("  NOTHING CHECKED -- this proves nothing. Do not rely on it.")
    elif suspect == 0:
        print("  Every sampled row agrees with a Python-written UTC stamp.")
        print("  The erp database clock was UTC for all of them.")


def _ruler(orders: list[dict], deals: list[dict]) -> None:
    """erp's MySQL-written created_at against crm's Python-written UTC one."""
    by_order: dict[str, dict] = {}
    for deal in deals:
        found = ORDER_NO.search(str(deal.get("title", "")))
        if found:
            by_order.setdefault(found.group(0).upper(), deal)

    print("\n--- THE RULER: erp created_at (MySQL) vs crm created_at (Python UTC) ---")
    print("  crm writes datetime.utcnow() -- naive UTC by construction, no clock can move it.")
    print("  A gap of seconds means the erp database clock was UTC for that row.")
    print("  A gap near +8h means that row was written under a local-time clock.")
    checked = suspect = 0
    worst = 0.0
    for order in orders:
        doc = str(order.get("document_no", "")).upper()
        deal = by_order.get(doc)
        if not deal:
            continue
        erp_at, crm_at = _parse(order.get("created_at")), _parse(deal.get("created_at"))
        if erp_at is None or crm_at is None:
            continue
        checked += 1
        gap = (erp_at - crm_at).total_seconds()
        worst = max(worst, abs(gap))
        if abs(gap) > SUSPECT_GAP:
            suspect += 1
            print(f"  SUSPECT {doc:18s} erp {order.get('created_at')} "
                  f"crm {deal.get('created_at')} gap {gap / HOUR:+.2f}h")
    print(f"  paired {checked} orders with their deal, {suspect} suspect")
    if checked == 0:
        print("  NOTHING PAIRED -- this proves nothing. Do not rely on it.")
    elif suspect == 0:
        print(f"  All {checked} agree (worst gap {worst:.0f}s). Those rows are UTC.")


def _rows(payload) -> list[dict]:
    """The list of records, whatever envelope crm_os wrapped it in this time.

    Its routers hand-build their responses (`utils/response.py:7`) rather than
    going through a response model, so the key is not the same on every route.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "contacts", "deals"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
            if isinstance(inner, dict):
                return _rows(inner)
    return []


def _all_pages(client, path: str, *, page_size: int = 100, limit: int = 10) -> list[dict]:
    """Every row, not just the newest page. `limit` is a stop, not an estimate."""
    rows: list[dict] = []
    for page in range(1, limit + 1):
        payload = client.get(path, params={"page": page, "page_size": page_size})
        items = payload.get("items", [])
        rows.extend(items)
        if len(items) < page_size:
            break
    return rows


def main() -> None:
    erp, crm = ErpClient(), CrmClient()

    # erp_os caps page_size at 100, so walk the pages -- the whole point is to
    # judge the oldest rows, and one page would only ever show the newest.
    orders = _all_pages(erp, "/api/sales-orders")
    invoices = _all_pages(erp, "/api/invoices")
    deals = _rows(crm.get("/api/deals"))
    contacts = crm.get("/api/contacts", params={"page_size": 100})
    contacts = _rows(contacts)
    print(f"erp: {len(orders)} sales orders, {len(invoices)} invoices")
    print(f"crm: {len(deals)} deals, {len(contacts)} contacts")

    _shape("erp sales order", orders, [
        "document_no", "business_date", "created_at", "updated_at", "confirmed_at",
    ])
    _every_field("erp sales order", orders)
    _every_field("erp invoice", invoices)
    _every_field("crm deal", deals)
    _every_field("crm contact", contacts)

    _ruler(orders, deals)
    _detail_ruler(erp, orders)

    _span("erp sales order", orders, "created_at")
    _span("crm deal", deals, "created_at")
    _span("crm contact", contacts, "created_at")

    _future("erp sales order", orders, ["created_at", "updated_at"])
    _future("crm deal", deals, ["created_at", "updated_at"])
    _future("crm contact", contacts, ["created_at", "updated_at"])

    # One order in full: the list serializer may not carry every field the
    # detail one does, and confirmed_at came back null for all of them.
    if orders:
        detail = erp.get(f"/api/sales-orders/{orders[0]['id']}")
        print(f"\n--- erp sales order {orders[0].get('document_no')} in full ---")
        for key, value in sorted(detail.items()):
            if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
                print(f"  {key:22s} {value!r}")


if __name__ == "__main__":
    main()
