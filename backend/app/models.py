from pydantic import BaseModel


class BotSummary(BaseModel):
    id: str
    name: str
    description: str
    icon: str


class BotDetail(BaseModel):
    id: str
    name: str
    description: str
    icon: str


class IdentifyRequest(BaseModel):
    phone: str
    lang: str = "en"


class ChatTurn(BaseModel):
    role: str
    content: str


class IdentifyResponse(BaseModel):
    """Who the web visitor is, and whatever conversation they already have.

    `bot` and `history` come back filled in when this number has been talking to
    us on WhatsApp: same number, same Redis record, so the laptop picks the
    conversation up where the phone left it.
    """

    key: str
    bot: BotDetail | None = None
    history: list[ChatTurn] = []


class SelectBotRequest(BaseModel):
    bot_id: str
    lang: str = "en"


class SelectBotResponse(BaseModel):
    greeting: str
    quick_questions: list[str]


class SendMessageRequest(BaseModel):
    message: str


class SendMessageResponse(BaseModel):
    reply: str


class ResetResponse(BaseModel):
    status: str


# --- the audit log, read back (task 37.1) ------------------------------------


class ConversationSummary(BaseModel):
    """One run of one demo, as it appears in a list of them."""

    conversation_id: str
    key_id: str
    display_name: str | None = None
    channel: str
    bot_id: str
    messages: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    api_turns: int
    started_at: str
    last_at: str


class ToolCallRecord(BaseModel):
    tool: str
    tool_use_id: str
    input: dict | None = None
    output: str | None = None
    duration_ms: int | None = None
    status: str
    at: str


class TranscriptMessage(BaseModel):
    """One message, with whatever the bot did between reading it and answering."""

    id: int
    role: str
    content: str
    source: str
    at: str
    tool_calls: list[ToolCallRecord] = []


class ConversationDetail(BaseModel):
    conversation_id: str
    key_id: str
    display_name: str | None = None
    channel: str
    bot_id: str
    messages: list[TranscriptMessage]
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    api_turns: int


class HistoryPage(BaseModel):
    conversations: list[ConversationSummary]
    # What the caller asked for, echoed so a page knows whether to offer "more".
    limit: int
    offset: int
