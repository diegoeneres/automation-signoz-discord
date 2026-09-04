from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_webhook_url: SecretStr
    signoz_webhook_token: SecretStr
    sms_recipients: str = ""
    twilio_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: SecretStr = SecretStr("")
    twilio_from_number: str = ""
    twilio_sms_recipients: str = ""
    twilio_sms_template: str = ""
    twilio_api_base_url: str = "https://api.twilio.com/2010-04-01"
    database_path: str = "data/service.db"

    @property
    def twilio_recipients(self) -> list[str]:
        return [number.strip() for number in self.twilio_sms_recipients.split(",") if number.strip()]

    @property
    def critical_sms_recipients(self) -> list[str]:
        configured = self.sms_recipients or self.twilio_sms_recipients
        return [number.strip() for number in configured.split(",") if number.strip()]

    @property
    def sms_enabled(self) -> bool:
        return self.twilio_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
