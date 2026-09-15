"""Autoplay (task 29): scene 1 played from the console, with nobody typing.

The customer's lines are the only thing scripted. Each one is sent down the web
chat's own path -- `chat.send_message`, the function a visitor's browser calls --
so the model decides what to do with it, the tools really run, and the ERP order
and the CRM card that come out of it are real. The console follows the newest
conversation, so it shows this one without being told to.

Why the web path and not WhatsApp: a scripted line "from" a phone would put the
bot's replies on a real handset with nothing the customer said above them. The
price is what the web channel cannot do -- the invoice is issued in the ERP but
no PDF is sent, and there is no push -- which is also what the web chat does.

A script cannot listen, so it does the next best thing: a line whose work the
bot has already done in this run is skipped. The model often places the order
the moment it has the customer's details, and "yes, place it" after that would
read as a customer who was not paying attention.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from app.config import settings
from app.console import events
from app.models import AutoplayState, SelectBotRequest, SendMessageRequest
from app.services.user_store import identity

logger = logging.getLogger(__name__)

BOT_ID = "retail"
LANG = "zh"
# Before each line, so the room has read the reply the line answers. Long enough
# to read two sentences off a projector, short enough that nobody reaches for
# the keyboard.
PAUSE_SECONDS = 6.0


@dataclass(frozen=True)
class Step:
    say: str
    # The tool whose successful call makes this line unnecessary.
    unless_done: str = ""


# Scene 1 (tasks/todo.md, batch 01): a rojak opening, a change of mind, an order,
# an invoice. The third line carries everything an order for a stranger needs --
# a name, that they are buying for themselves, and where it goes -- because the
# bot asks for those before opening an account and a script cannot answer a
# question it did not expect. On a run after the first the account exists and
# the bot does not ask; the details are then simply the delivery address.
SCRIPT: tuple[Step, ...] = (
    Step("Boss 这个 earbuds 还有 stock 吗? 我要 2 个, 可以 COD 吗?"),
    Step("算了，改成 3 个"),
    Step("OK 就 3 个，帮我下单。我叫陈家明，个人买的，送到 No. 88, Jalan Ampang, 50450 Kuala Lumpur"),
    Step("对，没问题，下单吧", unless_done="erp_create_sales_order"),
    Step("好，发票也开给我", unless_done="erp_generate_einvoice"),
)

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_state = AutoplayState(total=len(SCRIPT))


def state() -> AutoplayState:
    with _lock:
        return _state.model_copy()


def is_running() -> bool:
    return state().running


def _update(**changes) -> None:
    global _state
    with _lock:
        _state = _state.model_copy(update=changes)


def _done(tool: str, key_id: str, since: int) -> bool:
    """Has this customer's run already got a successful call to `tool`?

    Successful means JSON came back: every tool here answers a refusal or an
    outage in words, and neither of those is an order.
    """
    return any(
        event.type == events.TOOL_END
        and event.tool == tool
        and event.key_id == key_id
        and event.status == "ok"
        and (event.output or "").lstrip().startswith("{")
        for event in events.since(since)
    )


def play() -> None:
    """Run the whole script in this thread. `start` is the one that returns."""
    # Imported here: the router imports this module, and the chat router is the
    # path being driven, not a dependency of the console.
    from app.routers import chat

    key_id = identity(settings.autoplay_phone)
    _stop.clear()
    _update(
        running=True, step=0, total=len(SCRIPT), skipped=0, stopped=False, error=None, key_id=key_id
    )
    since = events.latest_seq()
    try:
        chat.select_bot(key_id, SelectBotRequest(bot_id=BOT_ID, lang=LANG))
        for number, step in enumerate(SCRIPT, 1):
            if _stop.wait(PAUSE_SECONDS):
                _update(stopped=True)
                return
            if step.unless_done and _done(step.unless_done, key_id, since):
                _update(step=number, skipped=state().skipped + 1)
                continue
            _update(step=number)
            chat.send_message(key_id, SendMessageRequest(message=step.say))
        if _stop.is_set():
            _update(stopped=True)
    except Exception as exc:  # a dead turn must not leave the button stuck on "playing"
        logger.exception("autoplay stopped at step %s", state().step)
        _update(error=f"{type(exc).__name__}: {exc}")
    finally:
        _update(running=False)


def start() -> bool:
    """Play in the background. False if a run is already going.

    Marked running before the thread exists, under the lock, so a nervous
    double-click on the console cannot start two customers talking over each
    other in one conversation.
    """
    global _thread, _state
    with _lock:
        if _state.running:
            return False
        _state = _state.model_copy(update={"running": True})
    _thread = threading.Thread(target=play, name="autoplay", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    """Stop before the next line. A turn already with the model finishes."""
    _stop.set()


def join(timeout: float | None = None) -> None:
    if _thread is not None:
        _thread.join(timeout)


def reset() -> None:
    """Forget the last run. For tests."""
    global _state, _thread
    _stop.clear()
    _thread = None
    _state = AutoplayState(total=len(SCRIPT))
