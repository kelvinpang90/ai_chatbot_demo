from __future__ import annotations

import logging
import threading
import time
from typing import Any, NamedTuple

import httpx

logger = logging.getLogger(__name__)

# These are back-office lookups sitting in front of a customer waiting on WhatsApp;
# a slow one should surface as "I couldn't check that" rather than a hung reply.
REQUEST_TIMEOUT_SECONDS = 15

# crm_os hands back no TTL at all and erp_os only on the auth routes, so this is the
# 15 minutes both of them document.
DEFAULT_ACCESS_TTL_SECONDS = 15 * 60

# Renew a little early: a token that expires in flight comes back as a 401 the
# customer experiences as a dead bot.
EXPIRY_MARGIN_SECONDS = 60


# Everything httpx can throw at a caller that reads its responses whole.
#
# `HTTPError` is the base for transport failures and error statuses, but not for
# everything: `InvalidURL` derives straight from `Exception`, so a typo in
# ERP_BASE_URL sailed past the boundary as a raw httpx error. The rest of that
# family stays out on purpose -- `CookieConflict` needs cookies we never set, and
# the `StreamError` group needs a response we left unread, while `get`/`post`
# read theirs in full. Catching those would only hide our own bugs.
TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL)

# The subset that proves the request never left this process: no connection was
# ever established, so nothing can have been written on the far side. Every other
# transport failure happens with the request already in flight -- a read timeout
# is the ERP taking too long to answer, not the ERP declining to act -- and for a
# write the honest report is "we do not know", not "nothing happened".
NEVER_REACHED_THE_SERVICE = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.InvalidURL,
    httpx.UnsupportedProtocol,
    httpx.ProxyError,
)

# Long enough for a validation error naming the field, short enough to keep a
# stack trace and a console line readable.
MAX_ERROR_DETAIL_CHARS = 300


def _detail(response: Any) -> str:
    """Whatever the service said about the failure, trimmed."""
    try:
        return str(response.text)[:MAX_ERROR_DETAIL_CHARS]
    except Exception:  # pragma: no cover - a body we cannot read is not the story
        return ""


def _composed_by_the_service(response: Any) -> bool:
    """Did the application itself answer, or something standing in front of it?

    This is the difference between a 500 and a 502, and for a write it decides
    whether the row exists. erp_os and crm_os answer an error they handled with
    their own JSON envelope, and handling it means the request-scoped session was
    already rolled back when that response was written (erp_os: `get_db` rolls
    back and re-raises, the catch-all handler turns it into a 500
    INTERNAL_ERROR). An unknown customer_id is exactly this shape -- a foreign
    key violation, not a validation error -- so treating it as "the order might
    exist" would forbid the one retry that could still make the sale.

    A 502 or 504 from the proxy is an HTML page or nothing at all, and says
    nothing about what the application did with the request it is still holding.

    Known edge: a service that failed *after* committing, in an after-commit
    hook, also answers this way. erp_os only publishes such events on confirm,
    never on create, and mistaking a confirmed order for an unconfirmed one
    costs a phone call, while mistaking a booked order for a failed one costs a
    duplicate order.
    """
    try:
        return isinstance(response.json(), dict)
    except Exception:
        return False


class ApiClientError(RuntimeError):
    """Anything that stopped us getting an answer out of the back office.

    Every failure mode this class knows about arrives as this one type -- a refused
    login, a rate limit, a dead host, a timeout. Callers catch one thing, and a tool
    added later cannot forget to catch `httpx.ConnectError` the way the first three
    did.

    `may_have_landed` is the part that matters to a write. A read that fails is
    just a read that failed; a POST that fails can still have been committed, and
    the difference decides whether the customer is told "your order was not
    placed" or "we are checking". Defaults to False so a failure only claims
    uncertainty when something actually justifies it.
    """

    def __init__(self, message: str, *, may_have_landed: bool = False) -> None:
        super().__init__(message)
        self.may_have_landed = may_have_landed


class _Tokens(NamedTuple):
    access: str
    refresh: str
    expires_at: float


class JsonApiClient:
    """Email + password -> JWT, cached until it is nearly expired.

    erp_os and crm_os authenticate identically: `POST /api/auth/login` for a token
    pair, `POST /api/auth/refresh` to rotate it, access tokens good for 15 minutes,
    refresh tokens one-time-use. Logging in per call is not merely wasteful, it is
    self-defeating -- login is rate limited to 10/minute per IP and locks the account
    after 5 failures, while one demo makes more tool calls than that.

    Subclasses supply the base URL and the account. They override `_unwrap` when the
    service wraps its responses; crm_os puts everything under `data`, erp_os does not.
    """

    def __init__(self, *, name: str, base_url: str, email: str, password: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        # Replies run in FastAPI's sync threadpool, so two conversations can want a
        # token at the same moment. The lock keeps that from becoming two logins.
        self._lock = threading.Lock()
        self._tokens: _Tokens | None = None

    # -- hooks ---------------------------------------------------------------

    def _unwrap(self, payload: Any) -> Any:
        """Strip the response envelope. Bare JSON by default, which is erp_os."""
        return payload

    # -- auth ----------------------------------------------------------------

    def _post(self, path: str, json: dict) -> Any:
        try:
            response = httpx.post(
                f"{self.base_url}{path}", json=json, timeout=REQUEST_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except TRANSPORT_ERRORS as exc:
            # Covers the refused login and the rate limit as well as the dead socket:
            # none of httpx's exceptions derive from OSError.
            raise ApiClientError(f"{self.name} api: POST {path} failed: {exc}") from exc
        return self._unwrap(response.json())

    def _tokens_from(self, payload: Any) -> _Tokens:
        # Absent means "unspecified", not "zero" -- `or` would quietly turn a short
        # TTL the service really did send into the full 15 minutes.
        declared = payload.get("expires_in")
        ttl = DEFAULT_ACCESS_TTL_SECONDS if declared is None else int(declared)
        return _Tokens(
            access=payload["access_token"],
            refresh=payload["refresh_token"],
            expires_at=time.monotonic() + ttl - EXPIRY_MARGIN_SECONDS,
        )

    def _login(self) -> _Tokens:
        if not self._email or not self._password:
            # Say which knob is missing. Unset credentials otherwise surface as a
            # puzzling 401 from a service that is perfectly healthy.
            raise ApiClientError(
                f"{self.name} api: no credentials configured -- set "
                f"{self.name.upper()}_EMAIL and {self.name.upper()}_PASSWORD"
            )
        logger.info("%s api: logging in as %s", self.name, self._email)
        return self._tokens_from(
            self._post("/api/auth/login", {"email": self._email, "password": self._password})
        )

    def _renew(self, refresh: str) -> _Tokens:
        """Rotate the pair, falling back to a full login.

        Refresh tokens are one-time-use, so a container restart or a second client on
        the same account leaves ours already spent. That is expected, not an outage:
        log in again rather than failing the customer's question.
        """
        try:
            return self._tokens_from(
                self._post("/api/auth/refresh", {"refresh_token": refresh})
            )
        except (ApiClientError, KeyError, TypeError):
            logger.info("%s api: refresh rejected, logging in again", self.name)
            return self._login()

    def _access_token(self, *, force_login: bool = False) -> str:
        with self._lock:
            if force_login or self._tokens is None:
                self._tokens = self._login()
            elif time.monotonic() >= self._tokens.expires_at:
                self._tokens = self._renew(self._tokens.refresh)
            return self._tokens.access

    # -- requests ------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> Any:
        """GET an authenticated endpoint."""
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> Any:
        """POST an authenticated endpoint.

        Shares the re-login retry with `get`, which needs justifying for a write:
        a 401 is returned by the auth dependency before the route body runs, so
        the retry cannot book the same order twice. Nothing else is retried -- a
        timeout mid-write may well have landed, and we would rather report a
        failure the human can check than create a second order.
        """
        return self._request("POST", path, json=json)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """One authenticated call, re-authenticating once if the token is stale.

        The expiry check in `_access_token` is a clock comparison; the 401 retry
        covers what a clock cannot see -- a revoked session, a restarted back end.
        """
        # Call httpx by attribute rather than holding a reference: the two verbs
        # stay independently patchable, which is how the tests raise real
        # transport failures at exactly one of them.
        send = httpx.get if method == "GET" else httpx.post
        for force_login in (False, True):
            token = self._access_token(force_login=force_login)
            try:
                response = send(
                    f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    **kwargs,
                )
            except TRANSPORT_ERRORS as exc:
                raise ApiClientError(
                    f"{self.name} api: {method} {path} failed: {exc}",
                    # A connection that was never made cannot have written
                    # anything; a request that went out and never came back can.
                    # A read cannot have written anything either, whatever
                    # happened to it -- the tool that priced an order from the
                    # catalogue asks the same client, and a slow catalogue must
                    # not be reported as an order that might exist.
                    may_have_landed=(
                        method != "GET" and not isinstance(exc, NEVER_REACHED_THE_SERVICE)
                    ),
                ) from exc
            if response.status_code == 401 and not force_login:
                continue
            if response.status_code >= 400:
                # Carry the service's own words: "insufficient stock" and "no such
                # customer" are different answers to give a waiting customer, and a
                # bare status code cannot tell them apart.
                raise ApiClientError(
                    f"{self.name} api: {method} {path} returned "
                    f"{response.status_code}: {_detail(response)}",
                    # A 4xx is the service refusing the request, so nothing was
                    # written -- and so is a 5xx the service composed itself,
                    # which it only does after rolling its transaction back. What
                    # is left is the gateway answering for a service that never
                    # said what it did.
                    may_have_landed=(
                        method != "GET"
                        and response.status_code >= 500
                        and not _composed_by_the_service(response)
                    ),
                )
            return self._unwrap(response.json())

        raise ApiClientError(f"{self.name} api: {method} {path} stayed unauthorized after re-login")
