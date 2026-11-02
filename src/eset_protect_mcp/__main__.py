"""Entry point: run the Starlette app (health + mounted MCP app) with uvicorn."""

from __future__ import annotations

import uvicorn

from eset_protect_mcp.config import settings
from eset_protect_mcp.server import create_app

app = create_app()


def main() -> None:
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
