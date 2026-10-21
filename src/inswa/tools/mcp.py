"""MCP client for the Forecast, Variance Analyzer and Explainability tools.

The server address comes from MCP__URL: the local mock server by default, the real tool
server by changing the config only.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_framework import MCPStreamableHTTPTool

from inswa.config import Settings
from inswa.infra.secrets import SecretProvider


async def create_mcp_tool(
    settings: Settings,
    *,
    name: str,
    allowed_tools: Sequence[str],
    secrets: SecretProvider | None = None,
) -> MCPStreamableHTTPTool:
    headers: dict[str, str] = {}
    if settings.mcp.api_key_secret and secrets is not None:
        token = await secrets.get(settings.mcp.api_key_secret)
        if not token:
            raise ValueError(
                f"Secret '{settings.mcp.api_key_secret}' for the MCP server could not be resolved."
            )
        headers["Authorization"] = f"Bearer {token}"
    return MCPStreamableHTTPTool(
        name=name,
        url=settings.mcp.url,
        allowed_tools=list(allowed_tools),
        load_prompts=False,
        request_timeout=settings.mcp.request_timeout,
        static_headers=headers or None,
    )
