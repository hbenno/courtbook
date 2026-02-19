"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "CourtBook"
    debug: bool = True
    secret_key: str = "dev-secret-change-in-production"
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://courtbook:courtbook@db:5432/courtbook"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    jwt_algorithm: str = "HS256"

    # Email / SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@courtbook.io"
    password_reset_expire_minutes: int = 30
    frontend_url: str = "http://localhost:5173"

    # Stripe (test mode)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # Tenant context (single-tenant for now, multi-tenant later)
    default_org_slug: str = "hackney-tennis"

    model_config = {"env_prefix": "CB_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
