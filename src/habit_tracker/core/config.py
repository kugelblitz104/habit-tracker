from typing import Union

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    database_url: str = ""
    sqlalchemy_echo: bool = False

    # for local development only
    secret_key: str = "secretsecretsecret"

    cors_origins: Union[list[str], str] = ["http://localhost:3000"]
    host: str = "0.0.0.0"
    port: int = 8080

    # extra="ignore": the shared .env also holds tooling vars that aren't app
    # settings (e.g. ZSCALER_CA_PATH for the Docker build/compose), so ignore
    # unknown keys instead of failing to start.
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    algorithm: str = "HS256"

    access_token_expiry_minutes: int = 30
    refresh_token_expiry_days: int = 7
    # Password-reset links are short-lived (they arrive by email immediately).
    reset_token_expiry_minutes: int = 30

    # --- Password-reset email delivery ---------------------------------------
    # Provider-agnostic SMTP. Works with Resend (smtp.resend.com), SendGrid,
    # Mailgun, etc. — switching providers is just env vars. When smtp_host is
    # blank (local dev), send_email() logs the reset link instead of sending,
    # so the whole flow is testable offline.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Habit Tracker <noreply@localhost>"

    # Frontend page the reset link points at; the emailed URL is
    # f"{reset_url_base}?token=...". Set to the deployed frontend in prod.
    reset_url_base: str = "http://localhost:3000/reset-password"

    # Fernet key (urlsafe base64, 32 bytes) used to encrypt integration PATs at
    # rest. Leave blank to derive a stable key from secret_key (works with no
    # extra config; note that rotating secret_key then invalidates stored PATs,
    # so users would re-enter them). Generate a dedicated key with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    integration_encryption_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            # Handle comma-separated string
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


settings = Settings()
