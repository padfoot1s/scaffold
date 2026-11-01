"""MCP client for the forecasting tool server (Forecast, Variance, Explainability, RCA, ...).

The server address comes from MCP__URL: the local mock server by default, the real tool
server on Azure Container Apps by changing the config only. With MCP__AUTH=entra each call
carries a bearer token for MCP__SCOPE issued to this process's identity (managed identity
when hosted).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_framework import MCPStreamableHTTPTool

from inswa.config import Settings


async def create_mcp_tool(
    settings: Settings,
    *,
    name: str,
    allowed_tools: Sequence[str],
    credential: Any = None,
) -> MCPStreamableHTTPTool:
    """Build one tool connection. Agents are built per request, so the token is fresh per request
    and a connection never outlives the request (or the caller) it was created for."""
    headers: dict[str, str] = {}
    if settings.mcp.auth == "entra":
        if credential is None:
            raise ValueError("MCP__AUTH=entra needs an Azure credential.")
        token = await credential.get_token(settings.mcp.scope)
        headers["Authorization"] = f"Bearer {token.token}"
    return MCPStreamableHTTPTool(
        name=name,
        url=settings.mcp.url,
        allowed_tools=list(allowed_tools),
        load_prompts=False,
        request_timeout=settings.mcp.request_timeout,
        # Forecast tools only read data. A tool that changes state (e.g. a retraining trigger)
        # must be served from a separate connection with approval_mode="always_require".
        approval_mode="never_require",
        static_headers=headers or None,
    )
