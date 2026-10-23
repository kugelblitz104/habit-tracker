from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    database_url: str = ""
    sqlalchemy_echo: bool = False

    # JWT signing key. Required: there is no default, so a missing or blank
    # SECRET_KEY in environment fails at startup.
    secret_key: str = Field(min_length=1)

    # cors_origins lived here but was never read; main.py reads CORS_ORIGINS
    # from the environment directly via os.getenv(). Don't re-add it here.

    # extra="ignore": the shared .env may hold tooling vars that aren't app
    # settings, so ignore unknown keys instead of failing to start.
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

    # When false, /auth/register returns 403 unless the user table is empty
    # (so a fresh instance can still create its first account).
    registration_enabled: bool = True

    # Header holding the client IP, for a proxy that sets it on every request
    # and overwrites any client-sent copy (Railway: X-Real-IP). Blank uses the
    # socket peer, which uvicorn rewrites from X-Forwarded-For per
    # FORWARDED_ALLOW_IPS.
    client_ip_header: str = ""

    # Frontend page the reset link points at; the emailed URL is
    # f"{reset_url_base}?token=...". Set to the deployed frontend in prod.
    reset_url_base: str = "http://localhost:3000/reset-password"

    # Fernet key (urlsafe base64, 32 bytes) used to encrypt integration PATs at
    # rest. Leave blank to derive a stable key from secret_key (works with no
    # extra config; note that rotating secret_key then invalidates stored PATs,
    # so users would re-enter them). Generate a dedicated key with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    integration_encryption_key: str = ""

    # --- Web Push (VAPID) ----------------------------------------------------
    # Blank disables reminders entirely: the scheduler does not start and
    # GET /push/vapid-public-key returns 404, so the front-end hides the
    # feature.
    vapid_private_key: str = ""
    vapid_subject: str = ""


settings = Settings()  # pyright: ignore[reportCallIssue]  # fields come from the environment
