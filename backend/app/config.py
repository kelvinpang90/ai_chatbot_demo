from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

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
    # about how a room behaves, not a technical constant. Two hours suits a demo
    # watched continuously; a real service desk that leaves conversations open
    # over lunch would want longer, and a rehearsal where you want to watch it
    # lapse wants about a minute.
    handover_idle_seconds: float = 2 * 60 * 60

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
    erp_base_url: str = "https://erp.kelvinpeng.com"
    erp_email: str = ""
    erp_password: str = ""

    crm_base_url: str = "https://crm.kelvinpeng.com"
    crm_email: str = ""
    crm_password: str = ""

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
