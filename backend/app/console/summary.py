"""What the demo actually did, written as a message the customer keeps.

The one thing a WhatsApp demo has that a web demo does not: when the meeting is
over, the whole conversation is still in the customer's own pocket. They show it
to a partner that evening without having to remember any of it. This turns that
from a nice property into a deliberate closing move -- a last message that counts
up what really happened and names the documents, so the transcript they scroll
back through has a receipt at the top of it.

Every number here comes out of the audit log, which is to say out of tool calls
that actually ran. That is the point rather than an implementation detail: the
whole demo argues that this bot does not make things up, and a closing summary
with an invented figure in it would undo the argument on the last line.
"""
from __future__ import annotations

import json
import logging
from typing import NamedTuple

from app.services.audit import audit_store

logger = logging.getLogger(__name__)

# How many document numbers get quoted per activity. Three is already more than
# a closing message wants to carry; the rest are in the transcript above it.
MAX_REFERENCES = 3

# A conversation that lasted forty seconds still took a minute of the customer's
# day, and "0 minutes" reads as a bug rather than as brevity.
MIN_MINUTES = 1

# How long a silence ends the sitting. A conversation_id lives from the moment a
# demo is picked off the menu until the customer types "menu" again, which can be
# most of a day: the first real one on file ran from 16:34 to 19:25, because
# somebody chose the retail bot in the afternoon and sent it a photo that
# evening. Summarising that as "in the last 171 minutes I..." is not a rounding
# error, it is a different claim -- so the sitting is the run of messages with no
# long gap in it, and the counts are drawn from the same stretch. Thirty minutes
# because a demo is watched continuously; a customer who has been away half an
# hour is in a new conversation whatever the id says.
IDLE_GAP_SECONDS = 30 * 60

# Pushes are left out on purpose: this message is one, and a summary that counted
# itself would be strange. Anything not listed below is simply not mentioned --
# the message is a sales artefact and not an audit, and the audit page has
# everything that happened whether it is named here or not.
IGNORED_TOOLS = ("notify.push",)


class Activity(NamedTuple):
    """One kind of thing worth telling the customer their bot did.

    `reference` is the key in that tool's JSON result that holds the document
    number it created -- the part that makes the claim checkable, because the
    customer can read SO-2026-00001 here and find it on the screen behind you.
    Empty where the tool creates no document.
    """

    tools: tuple[str, ...]
    reference: str
    zh: str
    # Singular and plural. The only one of the three languages that needs both:
    # Chinese has measure words rather than plurals, and Malay reduplicates only
    # for emphasis, which a count already provides.
    en: tuple[str, str]
    ms: str
    # Which back office this wrote to, if any. The closing line names the systems
    # that were actually touched: the first real run of this said "written into a
    # real ERP and CRM" on a demo where nothing had gone anywhere near the CRM,
    # which is a small lie in the one message whose whole job is being checkable.
    system: str = ""


ACTIVITIES = (
    Activity(
        ("erp_search_sku", "erp_get_inventory", "erp_find_order_by_sku"),
        "",
        "查了 {n} 次商品和库存",
        ("{n} live stock lookup", "{n} live stock lookups"),
        "{n} semakan stok langsung",
        "ERP",
    ),
    Activity(
        ("erp_create_customer",),
        # No reference on purpose: what this tool returns is the ERP's row id,
        # which means nothing to the customer and reads as a number about them
        # that they were not expecting anyone to have.
        "",
        "开了 {n} 个客户账户",
        ("{n} customer account opened", "{n} customer accounts opened"),
        "{n} akaun pelanggan dibuka",
        "ERP",
    ),
    Activity(
        ("erp_create_sales_order",),
        "order_no",
        "下了 {n} 张真实订单",
        ("{n} real order placed", "{n} real orders placed"),
        "{n} pesanan sebenar dibuat",
        "ERP",
    ),
    Activity(
        ("erp_generate_einvoice",),
        "invoice_no",
        "开了 {n} 张 e-Invoice",
        ("{n} e-Invoice issued", "{n} e-Invoices issued"),
        "{n} e-Invois dikeluarkan",
        "ERP",
    ),
    Activity(
        ("erp_create_credit_note",),
        "credit_note_no",
        "开了 {n} 张退款单",
        ("{n} refund note raised", "{n} refund notes raised"),
        "{n} nota kredit dikeluarkan",
        "ERP",
    ),
    Activity(
        ("crm_create_lead",),
        "",
        "留了 {n} 条 CRM 线索",
        ("{n} CRM lead recorded", "{n} CRM leads recorded"),
        "{n} petunjuk CRM direkodkan",
        "CRM",
    ),
    Activity(
        ("voice.transcribe",),
        "",
        "听懂了 {n} 条语音",
        ("{n} voice note understood", "{n} voice notes understood"),
        "{n} mesej suara difahami",
    ),
    Activity(
        ("image.download", "document.download"),
        "",
        "读了 {n} 份您发来的照片或文件",
        # No comma inside either phrase: they are read out of a comma-separated
        # list, and one more makes the sentence lose its footing.
        ("{n} photo or file of yours read", "{n} photos and files of yours read"),
        "{n} gambar atau fail anda dibaca",
    ),
)

KEEPSAKE_ZH = "这段对话就留在您手机里，随时可以翻给同事看。"
KEEPSAKE_EN = "This whole conversation stays on your phone - scroll back any time, or show it to a colleague."
KEEPSAKE_MS = "Perbualan ini kekal dalam telefon anda - tatal semula bila-bila masa, atau tunjukkan kepada rakan sekerja."


class Tally(NamedTuple):
    """What one demo amounted to. `lines` is one entry per activity that happened."""

    minutes: int
    counted: int
    lines: list[tuple[Activity, int, list[str]]]


def _reference(output: str | None, key: str) -> str | None:
    """The document number a tool call produced, if it produced one.

    Tool results are the JSON this project's tools return, so this is reading our
    own format rather than guessing at someone else's. A call that failed answers
    with a sentence instead, which is not JSON and is not counted anyway.
    """
    if not output or not key:
        return None
    try:
        parsed = json.loads(output)
    except (TypeError, ValueError):
        return None
    value = parsed.get(key) if isinstance(parsed, dict) else None
    return str(value) if value else None


def _sitting_began(stamps: list) -> object:
    """When the exchange being closed off actually started.

    Walked backwards from the newest message rather than taken from the oldest:
    what is being summarised is the sitting the room has just watched, and the
    conversation it belongs to may have started hours earlier. The first gap
    longer than `IDLE_GAP_SECONDS` is where it began.
    """
    started = stamps[-1]
    for earlier, later in zip(reversed(stamps[:-1]), reversed(stamps[1:])):
        if (later - earlier).total_seconds() > IDLE_GAP_SECONDS:
            break
        started = earlier
    return started


def tally(conversation_id: str) -> Tally | None:
    """Count up one conversation, or None if there is no record of it.

    None rather than an empty tally: a demo that was never written down and a
    demo in which nothing happened are different things, and only one of them is
    worth sending a message about.
    """
    if not audit_store.enabled:
        logger.warning("asked to summarise %s with no audit log configured", conversation_id)
        return None

    stamps = [
        row["created_at"]
        for row in audit_store.query(
            "SELECT created_at FROM chat_messages WHERE conversation_id = %s ORDER BY id",
            (conversation_id,),
        )
        if row.get("created_at")
    ]
    if not stamps:
        return None

    started = _sitting_began(stamps)
    minutes = max(MIN_MINUTES, round((stamps[-1] - started).total_seconds() / 60))

    # Scoped to the same stretch the minutes are: an order placed this morning is
    # not something "I just did", and counting it under a number drawn from the
    # last ten minutes would put the two halves of the sentence at odds.
    calls = audit_store.query(
        "SELECT tool, output FROM tool_calls"
        " WHERE conversation_id = %s AND status = 'ok' AND created_at >= %s ORDER BY id",
        (conversation_id, started),
    )

    lines = []
    counted = 0
    for activity in ACTIVITIES:
        matching = [call for call in calls if call["tool"] in activity.tools]
        if not matching:
            continue
        counted += len(matching)
        references: list[str] = []
        for call in matching:
            found = _reference(call["output"], activity.reference)
            if found and found not in references:
                references.append(found)
        lines.append((activity, len(matching), references[:MAX_REFERENCES]))

    return Tally(minutes=minutes, counted=counted, lines=lines)


def _phrase(activity: Activity, count: int, references: list[str], language: str) -> str:
    """One activity as a phrase, with its document numbers after it.

    The numbers read the same in all three languages -- which is the whole reason
    they are the part that makes this checkable -- but the brackets around them
    do not: full-width is what Chinese sets them in, and "1 order（SO-1）" in an
    English sentence looks like a font that failed to load.
    """
    if language == "zh":
        text = activity.zh.format(n=count)
        brackets = "（{}）"
    elif language == "ms":
        text = activity.ms.format(n=count)
        brackets = " ({})"
    else:
        text = (activity.en[0] if count == 1 else activity.en[1]).format(n=count)
        brackets = " ({})"
    return text + brackets.format(", ".join(references)) if references else text


def compose(tally: Tally) -> str:
    """The message itself, in all three languages.

    Separated by blank lines rather than the " / " every other canned line in
    this project uses. Those are one sentence and this is three paragraphs; run
    together with slashes it would be unreadable on the screen it is written for.
    """
    zh = "、".join(_phrase(*line, "zh") for line in tally.lines)
    en = ", ".join(_phrase(*line, "en") for line in tally.lines)
    ms = ", ".join(_phrase(*line, "ms") for line in tally.lines)

    # Only the back offices something was actually written to. Saying "ERP and
    # CRM" on a demo that never touched the CRM is a small lie in the one message
    # whose entire job is to be checkable -- and the first real run made it.
    systems = []
    for activity, _, _ in tally.lines:
        if activity.system and activity.system not in systems:
            systems.append(activity.system)

    if tally.lines and systems:
        head_zh = (
            f"📋 刚才这 {tally.minutes} 分钟里，我{zh}"
            f"——全部写进了真实的 {' 和 '.join(systems)}，不是演示数据。"
        )
        head_en = (
            f"📋 In the last {tally.minutes} minutes I did {en} - all of it written into a "
            f"real {' and '.join(systems)}, not a mock-up."
        )
        head_ms = (
            f"📋 Dalam {tally.minutes} minit tadi saya buat {ms} - semuanya ditulis ke dalam "
            f"{' dan '.join(systems)} sebenar, bukan data palsu."
        )
    elif tally.lines:
        # Something happened, but nothing that wrote to a back office: a photo
        # read, a voice note understood. Worth saying, not worth dressing up.
        head_zh = f"📋 刚才这 {tally.minutes} 分钟里，我{zh}。"
        head_en = f"📋 In the last {tally.minutes} minutes I did {en}."
        head_ms = f"📋 Dalam {tally.minutes} minit tadi saya buat {ms}."
    else:
        # Nothing was called, which happens in a conversation that stayed on
        # questions. Claiming otherwise is the one thing this message must not do.
        head_zh = f"📋 刚才我们聊了 {tally.minutes} 分钟。"
        head_en = f"📋 We talked for {tally.minutes} minutes just now."
        head_ms = f"📋 Kita berbual selama {tally.minutes} minit tadi."

    return "\n\n".join(
        (
            f"{head_zh}{KEEPSAKE_ZH}",
            f"{head_en} {KEEPSAKE_EN}",
            f"{head_ms} {KEEPSAKE_MS}",
        )
    )


def for_conversation(conversation_id: str) -> tuple[str, Tally] | None:
    """The closing message for one demo, with the tally it was built from."""
    counted = tally(conversation_id)
    return None if counted is None else (compose(counted), counted)
