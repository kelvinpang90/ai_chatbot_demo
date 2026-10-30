import json
import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# A slot in an approved template's body: `{{1}}`, `{{2}}`, ...
TEMPLATE_SLOT = re.compile(r"\{\{(\d+)\}\}")


class CrmTemplateParam(BaseModel):
    """One `{{n}}` slot of a CRM template, as the CRM's form shows it."""

    label: str = Field(min_length=1)
    max_len: int = Field(ge=1, le=1024)


class CrmTemplate(BaseModel):
    """One template the CRM may send (phase-three contract, section 5.3).

    `body` is Meta's approved wording copied by hand, which is exactly where a
    slot gets lost: then the CRM's preview and the history would read one thing
    and the visitor's phone another, and nothing at runtime would notice. So the
    slots have to be precisely `{{1}}`..`{{n}}`, n being the number of params.
    """

    name: str = Field(min_length=1)
    language: str = Field(min_length=1)
    category: str = Field(min_length=1)
    params: list[CrmTemplateParam]
    body: str = Field(min_length=1)

    @model_validator(mode="after")
    def _slots_match_params(self) -> "CrmTemplate":
        slots = {int(n) for n in TEMPLATE_SLOT.findall(self.body)}
        if slots != set(range(1, len(self.params) + 1)):
            raise ValueError(
                f"{self.name}/{self.language}: body must use exactly {{{{1}}}}..{{{{{len(self.params)}}}}}, "
                f"one per param; it uses {sorted(slots)}"
            )
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    # The model every bot answers with, unless a bot's JSON names one of its own.
    # Haiku by default (2026-09-14, the owner's call on cost): about a fifth of
    # Opus 5 per token. Until that day each bot hard-coded its model and this
    # setting was dead weight -- see test_no_bot_hard_codes_a_model_so_the_setting_decides.
    anthropic_model: str = "claude-haiku-4-5"

    # Transcription (task 36). Declared ahead of the code that reads it because
    # an undeclared key with a value in `.env` is not ignored -- it fails
    # validation and the process does not start. (An undeclared key with an
    # empty value is dropped, which is why the leftover DEMO_ACCESS_PASSWORD on
    # the VPS is harmless and this one would not have been.)
    openai_api_key: str = ""
    # Which model listens to the voice notes. Settable because the one thing that
    # cannot be tested from here is how well it handles a Malaysian customer
    # switching between three languages in one sentence -- if the real-phone run
    # says badly, the answer should be an env var rather than a code change.
    transcription_model: str = "whisper-1"

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_daily_msg_limit: int = 100
    # The published Flow that asks for a name, a date and a property (task 24).
    # Empty is a supported state, not a broken one: the bot then walks the same
    # three questions in chat instead of opening a form. That is the degrade path
    # the plan asks for, and it is also what every test and the web chat line
    # get, since neither has a Flow to open.
    whatsapp_flow_id: str = ""
    # "draft" lets a Flow that has not been published yet be opened by whoever
    # owns the Meta app, which is the only way to try one before committing to
    # it. Anything else is sent as a normal published Flow. Meta rejects `draft`
    # for a Flow that IS published, so this has to go back to "published" after
    # the Flow goes live -- hence a setting rather than a constant.
    whatsapp_flow_mode: str = "published"
    # Meta will hand us documents up to 100MB; anything past this is bigger than we
    # can put in front of the model, so refuse it before pulling it into memory.
    # Five is Anthropic's own ceiling for a single image, which is what this cap
    # was sized against.
    whatsapp_media_max_bytes: int = 5 * 1024 * 1024
    # A PDF is not an image and does not belong under the same number: scene 2b
    # asks the customer to pull out a file of their own on the spot, and a scanned
    # brochure is comfortably past five megabytes. Anthropic takes 32MB per
    # request, base64 costs a third on top, so sixteen raw lands safely inside it.
    whatsapp_document_max_bytes: int = 16 * 1024 * 1024
    # How long after an order the customer's phone buzzes (task 19). A setting
    # rather than a constant because it is a piece of stagecraft: too short and
    # it looks like part of the reply, too long and the room has moved on. The
    # number that reads as "it did that by itself" is found in front of an
    # audience, not here.
    push_delay_seconds: float = 30.0
    # How long a handover survives without the person doing anything (task 20).
    # A setting for the same reason the push delay is one: it is a judgement
    # about how a room behaves, not a technical constant. It was two hours, for
    # a demo watched continuously. From task 42.2 it is a day: agents now answer
    # these visitors from the CRM's inbox, and a reply there keeps the bot quiet
    # for 24 hours after it (D2 of the CRM phase-two design). There is one
    # takeover for the console and the CRM, so the console's is a day too (Q7).
    # A rehearsal where you want to watch it lapse still wants about a minute.
    handover_idle_seconds: float = 24 * 60 * 60
    # The number autoplay (task 29) talks as. Nobody's phone: it only ever goes
    # down the web chat, which sends nothing to a handset. The first run opens an
    # ERP account under it and every later run finds that account again, which
    # is why it is fixed rather than fresh each time -- a new number per run
    # would leave a new trade account behind per run.
    autoplay_phone: str = "60100000029"

    # 微信客服 (WeCom customer service). All four are secrets and all four default
    # to empty for the same reason the back-office passwords do -- this repository
    # is public. Empty is also what the callback route checks to decide the
    # channel is simply not configured, which is the state every deployment but
    # the demo one is in.
    #
    # Nothing has ever filled these in, and on this account nothing can: calling
    # any 微信客服 API needs a trusted-IP allowlist, which cannot be configured
    # without a domain filed to the enterprise, which a Malaysian domain on an
    # overseas VPS cannot be. tasks/wecom-kf-plan.md has the whole chain and what
    # a filing would cost. Until then the callback route answers 503 and this
    # channel is inert.
    wecom_corpid: str = ""
    wecom_secret: str = ""
    wecom_token: str = ""
    wecom_encoding_aes_key: str = ""

    # The two back offices the retail demo reads and writes. Neither offers an API
    # key, only an email and a password, so those come from the environment and have
    # no default: this repository is public, and a default here is a published
    # password. The base URLs are not secrets and stay.
    erp_base_url: str = "https://erp.acuventech.com"
    erp_email: str = ""
    erp_password: str = ""

    crm_base_url: str = "https://crm.acuventech.com"
    crm_email: str = ""
    crm_password: str = ""

    # Every WhatsApp visitor's conversation, pushed to the CRM's inbox (task
    # 40.1, `services/crm_events.py`). Off by default: switched off, nothing is
    # queued and no thread starts, so deploying this changes nothing until the
    # CRM side is live and both ends hold the same secret. Switched on without
    # REDIS_URL or the secret, it says so once at startup and stays off.
    crm_events_enabled: bool = False
    # Not a secret, and only reachable inside the Docker networks the two
    # containers share -- the container name is the one infra_nginx proxies to.
    crm_events_url: str = "http://crm_os-backend-1:8000/internal/chatbot/events"
    # The HMAC key, the same value as the CRM's CHATBOT_EVENTS_SECRET. This
    # repository is public: never give it a default.
    crm_events_secret: str = ""
    # The other direction (task 41.1): the CRM asking us to send its agents'
    # replies, `routers/internal_crm.py`. Checks the CRM's CHATBOT_SEND_SECRET,
    # which must be a different value from the one above. Empty means every
    # /internal/crm/* request is refused with 503 -- there is no separate switch.
    # The previous key is only for rotating: either one passes while both are set.
    crm_send_secret: str = ""
    crm_send_secret_previous: str = ""
    # The templates the CRM may send outside the 24-hour window (task 46,
    # `services/crm_templates.py`): one line of JSON. Empty is a supported
    # state -- the CRM shows "no templates" and every send-template is a 422 --
    # and stays empty until Meta marks a template Active. Checked at startup:
    # a body whose slots do not match its params stops the process, on
    # purpose, rather than send visitors one wording and file another.
    crm_templates: Annotated[list[CrmTemplate], NoDecode] = []

    @field_validator("crm_templates", mode="before")
    @classmethod
    def _json_or_nothing(cls, value):
        # Decoded here rather than by pydantic-settings, which fails on the bare
        # `CRM_TEMPLATES=` that `.env.example` ships: empty means no templates.
        if isinstance(value, str):
            return json.loads(value) if value.strip() else []
        return value

    @field_validator("crm_templates")
    @classmethod
    def _one_entry_per_template(cls, value: list[CrmTemplate]) -> list[CrmTemplate]:
        seen = set()
        for template in value:
            key = (template.name, template.language)
            if key in seen:
                raise ValueError(f"CRM_TEMPLATES lists {template.name}/{template.language} twice")
            seen.add(key)
        return value

    # The shared infra_redis, where customer profiles live. Empty on purpose:
    # unset means "keep everything in memory", which is how this service ran
    # before there was a Redis and how it has to keep running if there is not
    # one. Both compose files set it.
    redis_url: str = ""

    # The shared infra_mysql, where the audit log lives: every message, every
    # tool call, every token bill, kept past the seven days Redis gives a profile
    # and past the 200 events the console holds in memory. Empty on purpose and
    # for the same reason as REDIS_URL -- unset means the log is simply off, which
    # is what the test suite and any deployment without the shared infrastructure
    # get. Shape: mysql://user:password@infra_mysql:3306/ai_chatbot
    mysql_url: str = ""

    # A second database on the same infra_mysql, where the property and food
    # demos keep their own back office (task 22). Separate from the audit log's
    # because the two have opposite lifecycles: the audit log is a record kept on
    # purpose, and this is demo state that wants truncating between showings.
    # Unset means those verticals have no back office -- but unlike the audit
    # log, which goes quietly dark, the first call says so out loud, because a
    # booking that silently went nowhere is worse than one that failed.
    # Shape: mysql://user:password@infra_mysql:3306/ai_chatbot_verticals
    verticals_mysql_url: str = ""

    # Guards everything under /console: the live tool feed, and from task 37.1
    # the audit log behind it. Empty means the console is closed rather than
    # open -- the opposite of how the chat routes read an empty password, and
    # deliberately so. The chat side shows a stranger a demo; this side shows
    # them every customer's transcript, real ERP order data included. A
    # deployment that forgets to set this should lose a feature, not leak.
    console_token: str = ""

    internal_shared_secret: str = ""

    # The director's console. Until task 12 nothing forwarded /console/, so the
    # tool feed was protected by being unreachable; now that nginx forwards it,
    # that accident is gone and this is the only thing between the public and a
    # live stream of ERP orders and customer records. Empty means the stream
    # refuses everyone -- an unset secret must never read as "no gate needed".
    # This is deliberately not a revival of the site-wide password removed on
    # 2026-09-05: the customer's chat stays open, only this stream is closed.
    console_token: str = ""


settings = Settings()
