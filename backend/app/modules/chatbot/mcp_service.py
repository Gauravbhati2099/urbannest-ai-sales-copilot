import os

from app.modules.chatbot.mcp_server import create_mcp_application

if os.getenv("MCP_ENABLED", "false").strip().lower() not in {"1", "true", "yes"}:
    raise RuntimeError("Set MCP_ENABLED=true to start the standalone MCP service")


server, app = create_mcp_application()
