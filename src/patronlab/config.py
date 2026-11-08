"""Typed settings from environment variables and .env."""

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ASYNC_DRIVER = "postgresql+asyncpg://"
_KNOWN_PREFIXES = ("postgres://", "postgresql://", "postgresql+psycopg://")


def normalize_database_url(value: str) -> str:
    """Adapts a provider URL (Render, Neon, Fly) to the asyncpg driver.

    libpq options asyncpg does not understand are translated: sslmode becomes
    ssl, and channel_binding is dropped (asyncpg negotiates it on its own).
    """
    for prefix in _KNOWN_PREFIXES:
        if value.startswith(prefix):
            value = _ASYNC_DRIVER + value.removeprefix(prefix)
            break
    parts = urlsplit(value)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode and "ssl" not in query:
        query["ssl"] = sslmode
    return urlunsplit(parts._replace(query=urlencode(query)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_expire_days: int = 7
    cors_origins: list[str] = ["http://localhost:4200"]
    # Largest image accepted for palette extraction, in bytes.
    max_image_bytes: int = 4 * 1024 * 1024
    # GraphiQL explorer at /graphql: handy for the demo, can be turned off.
    graphiql: bool = True

    @field_validator("database_url")
    @classmethod
    def use_async_driver(cls, value: str) -> str:
        return normalize_database_url(value)

    @field_validator("jwt_secret")
    @classmethod
    def secret_is_long(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT secret must have at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
