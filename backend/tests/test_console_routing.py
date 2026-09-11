"""Every console route has to be named in three places, and only one of them
is Python (task 19.1).

The backend declares a route; `frontend/nginx.conf` has to proxy it or the
deployed site answers from the SPA instead; `frontend/vite.config.ts` has to
proxy it or `npm run dev` does the same thing locally. Nothing catches a missing
entry: a GET comes back as index.html with a 200 on it, and a POST comes back
405. Task 19.1 shipped a console button that was unreachable in production for
exactly this reason, and it was found by curling the live site rather than by
anything in this suite.

So this suite knows about it now. The test reads the two config files out of the
repository rather than mocking them, which is the only way it can be true about
what will actually be deployed.
"""
import re
from pathlib import Path

import pytest

from app.routers.console import router

# Routes deliberately left unproxied. `/console` itself is the page the SPA
# renders, and nothing under the prefix should become backend surface by
# accident -- see the note in nginx.conf about naming paths rather than the
# prefix.
NOT_PROXIED: frozenset[str] = frozenset()


def _repo_root() -> Path | None:
    """The checkout, found by looking for the file we are about to read.

    Searched for rather than assumed: the tests are run against a mount whose
    shape is up to whoever ran them, and a hard-coded `parents[2]` would turn
    "the frontend is not mounted" into a failure about the wrong thing.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "frontend" / "nginx.conf").exists():
            return parent
    return None


def _console_paths() -> set[str]:
    """Every console route, as the fixed part of its path.

    Cut at the first `{`: `/console/history/{conversation_id}` is served by a
    prefix rule on `/console/history`, and matching the template literally would
    report a hole that is not there.
    """
    paths = set()
    for route in router.routes:
        path = getattr(route, "path", "")
        if path.startswith("/console"):
            paths.add(path.split("{")[0].rstrip("/"))
    return paths


def _covered(path: str, proxied: set[str]) -> bool:
    """Whether a proxy rule on one of `proxied` would carry this path.

    Both nginx's prefix locations and vite's proxy keys match by prefix, so a
    rule on `/console/history` answers for everything under it.
    """
    return any(path == rule or path.startswith(rule.rstrip("/") + "/") for rule in proxied)


@pytest.fixture
def _repo():
    root = _repo_root()
    if root is None:
        pytest.skip("frontend/ is not on this mount, so its config cannot be read")
    return root


def test_every_console_route_is_proxied_by_the_deployed_nginx(_repo):
    """The failure this exists for: deployed, gated, and answering from the SPA."""
    config = (_repo / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    # Both spellings the file uses: `location = /x {` is exact, `location /x {`
    # is a prefix.
    proxied = set(re.findall(r"location\s+(?:=\s+)?(/console\S*)\s*\{", config))

    missing = sorted(
        path for path in _console_paths() - NOT_PROXIED if not _covered(path, proxied)
    )

    assert not missing, (
        f"{missing} reach the backend locally and the SPA in production. "
        "Add a location block to frontend/nginx.conf."
    )


def test_every_console_route_is_proxied_by_the_dev_server(_repo):
    """The same hole one layer up: without this, `npm run dev` serves index.html
    to a fetch and the developer debugs the wrong thing for twenty minutes."""
    config = (_repo / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    proxied = set(re.findall(r"'(/console[^']*)'\s*:", config))

    missing = sorted(
        path for path in _console_paths() - NOT_PROXIED if not _covered(path, proxied)
    )

    assert not missing, (
        f"{missing} are not in the vite proxy map, so they will not work under "
        "`npm run dev`. Add them to frontend/vite.config.ts."
    )


def test_the_route_list_is_not_empty(_repo):
    """A guard on the guard: if `_console_paths` ever stopped finding anything,
    both tests above would pass by having nothing to check."""
    assert len(_console_paths()) >= 4
