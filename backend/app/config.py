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

    demo_access_password: str = ""

    internal_shared_secret: str = ""


settings = Settings()
