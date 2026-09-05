from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field, fields

from app.config import settings
from app.services import phone
from app.session_store import MAX_HISTORY_MESSAGES, Message

logger = logging.getLogger(__name__)

KEY_PREFIX = "chat:user:"

# A customer who came back the next morning should be recognised; one from a
# demo two months ago should not still be on file. Seven days, pushed forward on
# every write, so an active conversation never expires underneath itself.
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60

# Redis is one hop away on data_net, so a second is already generous. The
# customer is watching a typing indicator while this runs: waiting out a default
# multi-second timeout on a box that is down would be worse than having no
# profile at all.
CONNECT_TIMEOUT_SECONDS = 1.0
OPERATION_TIMEOUT_SECONDS = 1.0

# Once it has failed, stop paying that timeout on every single message. Thirty
# seconds is short enough that a Redis restarted mid-demo is picked back up
# within a couple of turns, without anyone touching this service.
RETRY_AFTER_SECONDS = 30.0


@dataclass
class UserProfile:
    """What we remember about one customer, across conversations.

    The phone number is the identity wherever we are given one: WhatsApp puts it
    on every inbound message and from task 33 the web chat asks for one, so both
    channels reach the same record.

    Since 2026 Meta lets a customer hide their number behind a username, and
    those arrive with no phone number at all. Such a record is filed under the
    BSUID instead -- which is why what the record is keyed on is its own field
    rather than something read off `phone`.
    """

    # What this record is filed under: the phone number where we have one, the
    # BSUID where we do not.
    key_id: str
    # The number itself, and its absence is meaningful: both back offices are
    # searched by phone, so a record without one cannot be looked up in either.
    phone: str | None = None
    # Meta's business-scoped user id. Unique per business portfolio, stable
    # across a username change, present on every inbound message.
    user_id: str | None = None
    # The handle the customer picked. Worth greeting them by, but never an
    # identity: Meta lets them change it whenever they like.
    username: str | None = None
    bot_id: str | None = None
    display_name: str | None = None
    # Worth its weight on the second visit alone: the bot can open in the
    # language they used last time instead of guessing.
    language: str | None = None
    # The two that actually cost something to rebuild. Holding the ids means the
    # back offices are not re-searched every turn, and -- the reason they are
    # here -- that a second enquiry cannot land on a different customer than the
    # first one did.
    erp_customer_id: str | None = None
    crm_contact_id: str | None = None
    first_seen: float = 0.0
    last_seen: float = 0.0
    history: list[Message] = field(default_factory=list)
    # Free-form and keyed by bot id, deliberately unschematised: what is worth
    # remembering differs per industry (a delivery address for retail, a budget
    # for property), and four of the five bots have no tools yet. Fixing fields
    # now would be inventing them for scenes nobody has written. tasks/todo.md
    # task 31 lists what each bot is expected to keep when its turn comes.
    profile: dict[str, dict] = field(default_factory=dict)

    def add_message(self, role: str, content: str) -> None:
        """Append a turn, keeping the same window the in-memory session uses."""
        self.history.append(Message(role=role, content=content))
        del self.history[: max(0, len(self.history) - MAX_HISTORY_MESSAGES)]


_FIELD_NAMES = {f.name for f in fields(UserProfile)}


def identity(identifier: str) -> str:
    """The filing identity for a phone number or a BSUID.

    `+60 17-394 8123` from a CRM record, `60173948123` from a WhatsApp webhook
    and `017-3948123` typed into the web chat are one customer, and the whole
    point of task 33 is that the number typed on a laptop finds the history from
    a phone. `phone.to_e164_digits` is what makes those three agree -- dropping
    the punctuation alone leaves the national form filed under a key of its own,
    which is the form a Malaysian is most likely to type.

    A BSUID is passed through whole. Reducing it to digits would throw away the
    country-code prefix that makes it unique, and there is no second spelling of
    one to reconcile: Meta issues the string, not a person typing it.
    """
    if phone.is_bsuid(identifier):
        return identifier.strip()
    digits = phone.to_e164_digits(identifier)
    if not digits:
        # Blank would file every anonymous visitor into one shared record, i.e.
        # show one customer another customer's conversation. Refuse instead.
        raise ValueError("a user profile needs a phone number or a user id")
    return digits


def _key(identifier: str) -> str:
    return f"{KEY_PREFIX}{identity(identifier)}"


def _serialise(profile: UserProfile) -> str:
    return json.dumps(asdict(profile), ensure_ascii=False)


def _deserialise(raw: str) -> UserProfile | None:
    try:
        data = json.loads(raw)
        # Empty turns are dropped on the way in, not merely kept out on the way
        # out. The Messages API rejects an empty text block, so one such turn on
        # file makes every later message from that number fail for as long as the
        # record lives -- seven days of a customer getting nothing but the
        # apology, fixable only by deleting their key by hand. Healing on read
        # means the records already spoiled recover by themselves.
        history = [
            Message(role=m["role"], content=m["content"])
            for m in data.get("history", [])
            if (m.get("content") or "").strip()
        ]
        # Unknown keys are dropped rather than passed on: a record written by a
        # newer build and read by an older container should cost us a field, not
        # a TypeError in the middle of a demo.
        known = {k: v for k, v in data.items() if k in _FIELD_NAMES}
        # Records written before what a record is filed under became a field of
        # its own carry a phone number and nothing else. They are live in Redis
        # for seven days at a time, so reading one has to mean recognising the
        # customer, not forgetting them and starting the demo over.
        key_id = known.get("key_id") or known.get("phone")
        if not key_id:
            logger.warning("discarding a user profile with nothing to file it under")
            return None
        return UserProfile(**{**known, "key_id": key_id, "history": history})
    except (TypeError, ValueError, KeyError):
        logger.warning("discarding an unreadable user profile", exc_info=True)
        return None


def _default_client(url: str):
    # Imported here, not at module scope, so a deployment without the package --
    # or without a Redis at all -- degrades to memory instead of failing to boot.
    import redis

    return redis.Redis.from_url(
        url,
        socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
        socket_timeout=OPERATION_TIMEOUT_SECONDS,
        decode_responses=True,
    )


class UserStore:
    """Customer profiles in the shared Redis, with memory as the safety net.

    Nothing here may be allowed to take the demo down. Every Redis call falls
    back to an in-process dictionary on failure, which is exactly how this
    service behaved before Redis existed: profiles live until the container
    restarts. Forgetting sooner is a far smaller loss than a cache getting to
    decide whether the bot can answer at all.

    Both backends hold the same serialised JSON, so a caller cannot come to
    depend on holding a live object -- mutating a profile without calling `save`
    loses the change in memory mode too, rather than only once Redis is on.
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        client_factory=_default_client,
    ) -> None:
        self._url = redis_url
        self._ttl = ttl_seconds
        self._client_factory = client_factory
        self._client = None
        self._offline_until = 0.0
        self._memory: dict[str, tuple[float, str]] = {}

    def get(self, identifier: str) -> UserProfile | None:
        """The record for this number or user id, or None if it is new to us."""
        raw = self._read(_key(identifier))
        return _deserialise(raw) if raw else None

    def get_or_create(self, identifier: str) -> UserProfile:
        """The record for this identifier, or a blank one for a first-timer.

        Nothing is written until `save`, so a wrong number that says one word
        and leaves does not become a stored customer.
        """
        existing = self.get(identifier)
        if existing is not None:
            return existing
        now = time.time()
        key_id = identity(identifier)
        blank = UserProfile(key_id=key_id, first_seen=now, last_seen=now)
        if phone.is_bsuid(key_id):
            blank.user_id = key_id
        else:
            blank.phone = key_id
        return blank

    def save(self, profile: UserProfile) -> None:
        """Persist the profile and push its expiry seven days out from now."""
        profile.last_seen = time.time()
        key = _key(profile.key_id)
        raw = _serialise(profile)
        client = self._redis()
        if client is not None:
            try:
                client.set(key, raw, ex=self._ttl)
                return
            except Exception:
                self._go_offline("write failed")
        self._memory[key] = (time.time() + self._ttl, raw)

    def delete(self, identifier: str) -> None:
        key = _key(identifier)
        client = self._redis()
        if client is not None:
            try:
                client.delete(key)
            except Exception:
                self._go_offline("delete failed")
        self._memory.pop(key, None)

    def reset(self) -> None:
        """Forget everything held in memory and re-open the connection. Tests."""
        self._memory.clear()
        self._client = None
        self._offline_until = 0.0

    def _read(self, key: str) -> str | None:
        client = self._redis()
        if client is not None:
            try:
                return client.get(key)
            except Exception:
                self._go_offline("read failed")
        return self._memory_read(key)

    def _memory_read(self, key: str) -> str | None:
        entry = self._memory.get(key)
        if entry is None:
            return None
        expires_at, raw = entry
        if expires_at <= time.time():
            # The fallback honours the same seven days. Redis would have dropped
            # this key, and a customer who is stale on one backend should not be
            # remembered on the other.
            del self._memory[key]
            return None
        return raw

    def _redis(self):
        """A client to use, or None meaning "go to memory for this one"."""
        if not self._url or time.time() < self._offline_until:
            return None
        if self._client is None:
            try:
                self._client = self._client_factory(self._url)
            except Exception:
                self._go_offline("could not build a client")
                return None
        return self._client

    def _go_offline(self, reason: str) -> None:
        self._client = None
        self._offline_until = time.time() + RETRY_AFTER_SECONDS
        logger.warning("user store falling back to memory: %s", reason, exc_info=True)


# An empty REDIS_URL means memory only, which is what the test suite and anyone
# running this without the shared infrastructure get.
user_store = UserStore(settings.redis_url)
