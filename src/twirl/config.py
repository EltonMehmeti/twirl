from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Hosted Postgres (Neon, Render) hands out postgres:// URLs; SQLAlchemy needs the driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


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
    request_rate_limit_per_hour: int = 20
    request_sla_hours: int = 24
    # Deployment
    storage_backend: str = "local"  # local | s3 | memory
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    cron_secret: str = ""  # enables POST /internal/jobs for an external scheduler
    basic_auth: str = ""  # "user:password" puts the whole site behind a login (staging)

    @field_validator("database_url")
    @classmethod
    def _driver(cls, value: str) -> str:
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
