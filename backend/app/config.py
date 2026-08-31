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

    # The two back offices the retail demo reads and writes. Both are demo systems
    # with no API key mechanism -- an email and a password is all they offer -- and
    # these accounts are already recorded in tasks/todo.md, so they default here
    # rather than becoming one more .env line to forget before a demo. Override per
    # environment if that ever stops being true.
    erp_base_url: str = "https://erp.kelvinpeng.com"
    erp_email: str = "admin@demo.my"
    erp_password: str = "Admin@123"

    crm_base_url: str = "https://crm.kelvinpeng.com"
    crm_email: str = "admin@crm.com"
    crm_password: str = "Admin123"

    demo_access_password: str = ""

    internal_shared_secret: str = ""


settings = Settings()
