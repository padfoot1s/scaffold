"""Run the local mock MCP server: python -m inswa.mock_mcp_server"""

import logging

from inswa.config import get_settings
from inswa.mock_mcp_server.server import build_server

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    logger.info("Mock MCP server on http://%s:%s/mcp", settings.mcp.mock_host, settings.mcp.mock_port)
    build_server().run(
        transport="streamable-http",
        host=settings.mcp.mock_host,
        port=settings.mcp.mock_port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
