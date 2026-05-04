from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_temperature: float = 0.0

    notion_api_key: str = ""
    notion_database_id: str = ""

    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""

    slack_bot_token: str = ""
    slack_channel: str = "#meeting-debriefs"

    # Comma-separated in .env: TEAM_MEMBERS=Alice Smith,Bob Jones
    team_members_str: str = ""

    max_validation_attempts: int = 3
    use_stub_mcp: bool = True

    @property
    def team_members(self) -> list[str]:
        if not self.team_members_str:
            return []
        return [m.strip() for m in self.team_members_str.split(",") if m.strip()]


settings = Settings()
