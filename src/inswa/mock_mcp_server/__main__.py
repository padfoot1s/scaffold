"""Run the local mock MCP server: python -m inswa.mock_mcp_server"""

from inswa.config import get_settings
from inswa.mock_mcp_server.server import build_server


def main() -> None:
    settings = get_settings()
    server = build_server(settings.mcp.mock_host, settings.mcp.mock_port)
    print(f"Mock MCP server on http://{settings.mcp.mock_host}:{settings.mcp.mock_port}/mcp")
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
