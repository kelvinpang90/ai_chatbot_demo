"""Reading a `mysql://` URL into the kwargs PyMySQL wants.

Shared rather than copied. There are two stores on the shared infra_mysql now --
the audit log and the verticals data -- and the parsing is not the boring part it
looks like: the password arrives percent-encoded, and handing MySQL the still
encoded form fails as `Access denied`, which reads like a credentials problem
rather than a parsing one. That cost a VPS session once. One parser means one
place for that to be right and one test standing guard over it.

What differs between callers is only the name in the log line, so that is the
argument.
"""
from __future__ import annotations

import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Short on purpose: this is a lookup on the same docker network standing between
# a customer and a reply, so failing fast beats waiting.
CONNECT_TIMEOUT_SECONDS = 2.0


def dsn(url: str, *, feature: str) -> dict | None:
    """Connection kwargs from a `mysql://user:pass@host:port/db` URL, or None.

    `feature` names what goes dark in the warning -- "the audit log", "the
    verticals store" -- because the line is the only thing a person reading
    `docker logs` gets, and "MYSQL_URL is not a mysql:// url" on its own does not
    say which of the two URLs is the broken one.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("mysql", "mysql+pymysql") or not parsed.hostname:
        logger.warning("not a mysql:// url; %s is off", feature)
        return None
    database = (parsed.path or "").lstrip("/")
    if not database:
        logger.warning("the url names no database; %s is off", feature)
        return None
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        # A generated password is very likely to contain reserved characters, so
        # the URL carries it percent-encoded and it is decoded back here.
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    }


def connect(dsn_kwargs: dict):
    """Open the connection.

    `import pymysql` deferred to call time, not module scope, so a deployment
    without the package -- or without a MySQL at all -- runs with these stores
    off instead of failing to boot.
    """
    import pymysql

    return pymysql.connect(**dsn_kwargs)
