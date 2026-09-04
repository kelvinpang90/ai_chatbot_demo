from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_daily_msg_limit: int = 100
    # Meta will hand us documents up to 100MB; anything past this is bigger than we
    # can put in front of the model, so refuse it before pulling it into memory.
    whatsapp_media_max_bytes: int = 5 * 1024 * 1024

    # 微信客服 (WeCom customer service). All four are secrets and all four default
    # to empty for the same reason the back-office passwords do -- this repository
    # is public. Empty is also what the callback route checks to decide the
    # channel is simply not configured, which is the state every deployment but
    # the demo one is in.
    #
    # The secret is not handed out until the callback config below is saved, and
    # WeCom verifies that callback the moment you save it. So on a first setup
    # these arrive in two rounds: token and key first, secret afterwards.
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

    demo_access_password: str = ""

    internal_shared_secret: str = ""


settings = Settings()
