"""Application configuration via Pydantic Settings. Fails fast at startup on missing/invalid values."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for pulse-data.

    All values are read from environment variables (case-insensitive).
    The app will refuse to start if required variables are missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # PostgreSQL — PULSE main database
    database_url: str = "postgresql+asyncpg://pulse:pulse@localhost:5432/pulse"

    # Kafka
    kafka_brokers: str = "localhost:9092"

    # ---- Source API Connectors ----

    # GitHub
    github_token: str = ""
    github_org: str = "webmotors-private"
    github_api_url: str = "https://api.github.com"

    # Jira Cloud
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_projects: str = ""  # Comma-separated project keys (e.g., "DESC,ENO,ANCR")

    # Jenkins
    jenkins_base_url: str = ""
    jenkins_username: str = ""
    jenkins_api_token: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Multi-tenancy — single default tenant in MVP
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"

    # Application
    app_name: str = "pulse-data"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    @property
    def async_database_url(self) -> str:
        """Ensure the database URL uses the asyncpg driver."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def kafka_broker_list(self) -> list[str]:
        return [b.strip() for b in self.kafka_brokers.split(",")]

    @property
    def jira_project_list(self) -> list[str]:
        """Parse comma-separated Jira project keys."""
        if not self.jira_projects:
            return []
        return [p.strip() for p in self.jira_projects.split(",") if p.strip()]


# Singleton — imported across the app
settings = Settings()
