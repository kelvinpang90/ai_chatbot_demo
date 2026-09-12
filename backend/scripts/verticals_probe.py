"""The verticals database, against a real MySQL rather than a fake cursor.

Task 22's acceptance, and re-runnable afterwards: create a table, write a row,
read it back, drop the table. The unit tests drive a fake DB-API connection, so
the one thing they cannot tell you is whether MySQL accepts the SQL as written --
utf8mb4 on a Chinese name, `DATETIME(3)` keeping its milliseconds, a `%s`
placeholder carrying an apostrophe through untouched.

It cleans up after itself, so it leaves no table behind in a database the demo
will later be shown out of.

Run it against the local stand-in. `scripts/` is not in the image -- the
Dockerfile copies only `app/` -- so it is mounted, and PYTHONPATH is set because
a script run by path does not put the working directory on it:

    docker compose up -d mysql
    docker compose run --rm --no-deps -e PYTHONPATH=/app -v "$PWD/backend/scripts:/app/scripts:ro" backend python scripts/verticals_probe.py

Connecting at all proves the second database exists, which on a fresh volume
means deploy/mysql-init/01-verticals.sql ran. Against any other MySQL, set
VERTICALS_MYSQL_URL in the environment instead.
"""
from __future__ import annotations

import sys
from datetime import datetime

from app.verticals import StoreUnavailable, store

PROBE_TABLE = """
    CREATE TABLE IF NOT EXISTS _probe (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        who VARCHAR(120) NOT NULL,
        note MEDIUMTEXT NOT NULL,
        seen_at DATETIME(3) NOT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Every awkward thing a real row will carry: a name that is not ASCII, an
# apostrophe that would end the string if it were interpolated rather than
# passed as a parameter, and a timestamp with milliseconds that has to survive
# the round trip intact.
WHO = "陈家明 O'Brien"
NOTE = "蒲种三房，60 万以内 -- viewing booked from WhatsApp"


def main() -> int:
    if not store.enabled:
        print("VERTICALS_MYSQL_URL is not set; nothing to probe.")
        return 2

    store.register(PROBE_TABLE)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    try:
        row_id = store.execute(
            "INSERT INTO _probe (who, note, seen_at) VALUES (%s, %s, %s)",
            (WHO, NOTE, stamp),
        )
        print(f"wrote row {row_id}")

        rows = store.query("SELECT * FROM _probe WHERE id = %s", (row_id,))
    except StoreUnavailable as failure:
        print(f"FAILED: {failure}")
        return 1
    finally:
        # Even on failure: a half-written probe table is exactly the kind of
        # thing that turns up on a screen during a demo.
        try:
            store.execute("DROP TABLE IF EXISTS _probe")
            print("dropped the probe table")
        except StoreUnavailable:
            print("WARNING: could not drop the probe table")

    if not rows:
        print("FAILED: the row was written and could not be read back")
        return 1

    row = rows[0]
    print(f"read back: {row}")

    problems = []
    if row["who"] != WHO:
        problems.append(f"who came back as {row['who']!r}, not {WHO!r}")
    if row["note"] != NOTE:
        problems.append(f"note came back as {row['note']!r}")
    if row["seen_at"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] != stamp:
        problems.append(f"seen_at came back as {row['seen_at']}, not {stamp}")

    if problems:
        for problem in problems:
            print(f"FAILED: {problem}")
        return 1

    print("OK: created a table, wrote a row, read it back unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
