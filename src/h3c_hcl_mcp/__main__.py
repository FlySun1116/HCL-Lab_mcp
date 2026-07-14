"""Entry point for h3c-hcl-mcp: starts the MCP stdio server."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """Launch the HCL-Lab MCP Server via stdio transport."""
    print("h3c-hcl-mcp v0.0.1 — starting...", file=sys.stderr)

    from h3c_hcl_mcp.mcp.server import main as server_main

    asyncio.run(server_main())


if __name__ == "__main__":
    main()
