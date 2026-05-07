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


_REAL_MCP_REQUIRED: dict[str, str] = {
    "NOTION_API_KEY":     "notion_api_key",
    "NOTION_DATABASE_ID": "notion_database_id",
    "JIRA_URL":           "jira_url",
    "JIRA_EMAIL":         "jira_email",
    "JIRA_API_TOKEN":     "jira_api_token",
    "JIRA_PROJECT_KEY":   "jira_project_key",
    "SLACK_BOT_TOKEN":    "slack_bot_token",
}


def validate_real_mcp_keys(s: Settings) -> None:
    """
    Raise ValueError listing every missing key when use_stub_mcp=False.
    Passes silently in stub mode or when all required keys are present.
    """
    if s.use_stub_mcp:
        return
    missing = [
        env_name
        for env_name, attr in _REAL_MCP_REQUIRED.items()
        if not getattr(s, attr, "")
    ]
    if missing:
        raise ValueError(
            "USE_STUB_MCP=false but the following required keys are not set: "
            + ", ".join(missing)
        )
