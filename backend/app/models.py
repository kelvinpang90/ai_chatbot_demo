from pydantic import BaseModel


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str


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
