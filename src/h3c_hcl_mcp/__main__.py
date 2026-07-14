"""Entry point for h3c-hcl-mcp: starts the MCP stdio server."""

from __future__ import annotations

import asyncio
import sys

from h3c_hcl_mcp.mcp.server import SERVER_NAME, VERSION


def main() -> None:
    """Launch the HCL-Lab MCP Server via stdio transport."""
    print(f"{SERVER_NAME} v{VERSION} -- starting stdio server...", file=sys.stderr)

    from h3c_hcl_mcp.mcp.server import main as server_main

    asyncio.run(server_main())


if __name__ == "__main__":
    main()
