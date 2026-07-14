"""Entry point for h3c-hcl-mcp: starts the MCP stdio server."""

from __future__ import annotations

import argparse
import asyncio
import sys

from h3c_hcl_mcp.mcp.server import SERVER_NAME
from h3c_hcl_mcp.version import VERSION


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments. Unknown arguments cause an error exit."""
    parser = argparse.ArgumentParser(
        prog="h3c-hcl-mcp",
        description=f"{SERVER_NAME} — MCP Server for H3C Cloud Lab",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        type=str,
        default=None,
        help="Path to YAML/JSON configuration file",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{SERVER_NAME} v{VERSION}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Launch the HCL-Lab MCP Server via stdio transport.

    Args:
        argv: CLI arguments (defaults to sys.argv[1:]).
    """
    args = _parse_args(argv)
    print(f"{SERVER_NAME} v{VERSION} -- starting stdio server...", file=sys.stderr)

    from h3c_hcl_mcp.mcp.server import main as server_main

    asyncio.run(server_main(config_path=args.config))


if __name__ == "__main__":
    main()
