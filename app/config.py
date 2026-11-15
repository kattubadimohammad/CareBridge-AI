import os
from pydantic import model_validator, Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    app_name: str = "CareBridge AI"
    environment: str = "development"
    app_secret_key: str = Field(
        default="carebridge-default-secret-key-change-me",
        validation_alias=AliasChoices("app_secret_key", "jwt_secret"),
    )
    log_level: str = "info"

    host: str = "0.0.0.0"
    port: int = 8080

    # Brute-force & PIN security settings
    max_pin_attempts: int = 5
    pin_lockout_minutes: int = 15

    # Medication scheduling & reminder engine settings
    dose_grace_period_minutes: int = 60
    reminder_window_minutes: int = 30

    # SQLite for local development; PostgreSQL / Cloud SQL for production
    database_url: str = "sqlite:///./carebridge.db"

    # Cloud Scheduler security token
    cron_api_key: str = "carebridge-cron-secret-token"

    # Email notification settings
    smtp_enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "CareBridge AI <notifications@carebridge.ai>"
    smtp_tls: bool = True
    smtp_timeout_seconds: int = 10
    appointment_reminder_hours: int = 48

    @model_validator(mode="after")
    def validate_production_secrets(self):
        """Reject insecure default secret key in production environments."""
        if self.environment == "production" and (
            not self.app_secret_key
            or self.app_secret_key == "carebridge-default-secret-key-change-me"
            or len(self.app_secret_key) < 32
        ):
            raise ValueError(
                "CRITICAL SECURITY CONFIGURATION: In production mode, APP_SECRET_KEY must be explicitly set "
                "to a secure random string (at least 32 characters) and cannot use the default placeholder."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
