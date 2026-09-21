"""Application settings, loaded from the environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- database ---
    database_url: str = "postgresql+psycopg://trainbuddy:trainbuddy@localhost:5433/trainbuddy"

    # --- Strava ---
    # Base URL migrates from www.strava.com/api/v3; the old host stops working in Jan 2027.
    strava_api_base: str = "https://api-v3.strava.com"
    strava_oauth_base: str = "https://www.strava.com/oauth"
    strava_client_id: str = ""
    strava_client_secret: str = ""
    strava_redirect_uri: str = "http://localhost:8000/auth/strava/callback"
    strava_scope: str = "read,activity:read_all"

    # --- Anthropic ---
    anthropic_api_key: str = ""
    agent_model: str = "claude-opus-5"
    text_model: str = "claude-haiku-4-5"

    # --- matching ---
    default_radius_km: float = 20.0
    max_radius_km: float = 50.0
    cluster_eps_km: float = 2.0
    cluster_min_activities: int = 3
    max_home_bases: int = 3

    # --- app ---
    session_secret: str = "change-me"
    enable_dev_login: bool = False
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
