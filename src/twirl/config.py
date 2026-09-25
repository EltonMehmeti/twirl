from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TWIRL_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://twirl:twirl@localhost:5433/twirl"
    secret_key: str = "dev-insecure-change-me"
    https_only: bool = False
    base_url: str = "http://localhost:8000"
    brand_name: str = "Vesha"
    sms_dev_echo: bool = False
    media_root: Path = Path("var/media")
    run_scheduler: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "Vesha <no-reply@vesha.local>"
    telegram_bot_token: str = ""
    telegram_admin_chat_id: str = ""
    trust_cf_connecting_ip: bool = False
    request_rate_limit_per_hour: int = 5
    request_sla_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
