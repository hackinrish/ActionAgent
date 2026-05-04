import os

# Set before any action_agent imports so pydantic-settings picks them up
os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder-key")
os.environ.setdefault("USE_STUB_MCP", "true")
