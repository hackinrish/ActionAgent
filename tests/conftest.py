import os
from pathlib import Path

# Load .env into the OS environment BEFORE pydantic-settings instantiates Settings().
# pydantic-settings prioritises os.environ over .env, so we must seed it here first.
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    from dotenv import dotenv_values
    for _k, _v in dotenv_values(_env_path).items():
        if _v:
            os.environ.setdefault(_k, _v)

# Fallbacks for CI / testing without a real .env
os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-key")
os.environ.setdefault("USE_STUB_MCP", "true")
