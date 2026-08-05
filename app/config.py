from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_webhook_url: SecretStr
    public_base_url: str
    ticket_signing_secret: SecretStr
    jira_base_url: str
    jira_email: str
    jira_api_token: SecretStr
    jira_project_key: str
    jira_issue_type: str = "Task"
    signoz_webhook_token: SecretStr
    database_path: str = "data/service.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
