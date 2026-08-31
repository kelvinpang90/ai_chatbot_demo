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


class ApiClientError(RuntimeError):
    """Anything that stopped us getting an answer out of the back office.

    Every failure mode this class knows about arrives as this one type -- a refused
    login, a rate limit, a dead host, a timeout. Callers catch one thing, and a tool
    added later cannot forget to catch `httpx.ConnectError` the way the first three
    did.
    """


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
        """GET an authenticated endpoint, re-authenticating once if the token is stale.

        The expiry check above is a clock comparison; the 401 retry covers what a
        clock cannot see -- a revoked session, a restarted back end.
        """
        for force_login in (False, True):
            token = self._access_token(force_login=force_login)
            try:
                response = httpx.get(
                    f"{self.base_url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except TRANSPORT_ERRORS as exc:
                raise ApiClientError(f"{self.name} api: GET {path} failed: {exc}") from exc
            if response.status_code == 401 and not force_login:
                continue
            if response.status_code >= 400:
                raise ApiClientError(
                    f"{self.name} api: GET {path} returned {response.status_code}"
                )
            return self._unwrap(response.json())

        raise ApiClientError(f"{self.name} api: GET {path} stayed unauthorized after re-login")
