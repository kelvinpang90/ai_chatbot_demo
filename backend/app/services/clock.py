"""The moment, spelled the way a MySQL DATETIME column wants it.

Extracted from `audit.py` when the verticals needed the same thing (task 23),
for the reason task 22 gave when it pulled `mysql_url.py` out of the same file:
two copies of a subtle rule are two chances for it to drift, and everything
below is a rule somebody learned the hard way.
"""
from __future__ import annotations

import time
from datetime import datetime


def sql_timestamp(at: float | None = None) -> str:
    """A moment in the container's local time, for a DATETIME(3) column.

    Local rather than UTC on purpose, and it is the compose files that make that
    safe: both set TZ=Asia/Kuala_Lumpur, so this agrees with the log lines beside
    it and with every other container vps_infra runs. A DATETIME keeps no
    timezone to correct it by afterwards, so the clock has to be right when the
    row is written -- an unset TZ files a 9pm demo under 13:00, and nothing in
    the stored value would ever say so.

    Written here rather than left to MySQL's own CURRENT_TIMESTAMP, which is the
    same decision seen from the other side: the database container's clock is not
    ours to set. The local `mysql:8` in docker-compose.yml has no TZ at all, so a
    column defaulted to its clock would be eight hours out -- which is precisely
    the bug tasks/erp-crm-timezone.md spent a day tracing through two other
    systems.

    Built through `datetime` rather than by taking the fraction of the float by
    hand: `int(seconds % 1 * 1000)` truncates a value the binary representation
    has already nudged downwards, so .938 was stored as .937. Off by a
    millisecond does not matter; a rounding bug in the column two rows are
    ordered by is worth not having.
    """
    seconds = time.time() if at is None else at
    return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
