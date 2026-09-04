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
