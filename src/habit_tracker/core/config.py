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

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    algorithm: str = "HS256"

    access_token_expiry_minutes: int = 30
    refresh_token_expiry_days: int = 7

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            # Handle comma-separated string
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


settings = Settings()
