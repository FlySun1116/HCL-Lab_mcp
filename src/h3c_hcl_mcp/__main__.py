"""Entry point for h3c-hcl-mcp: starts the MCP stdio server."""

from __future__ import annotations

import argparse
import asyncio
import sys

from h3c_hcl_mcp.mcp.server import SERVER_NAME, create_server
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
        help="Path to YAML or JSON configuration file",
    )
    parser.add_argument(
        "--projects-dir",
        metavar="DIR",
        type=str,
        action="append",
        default=None,
        dest="projects_dirs",
        help="Add a directory to scan for HCL projects (may be repeated)",
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

    # Build CLI overrides dict for settings
    cli_overrides: dict[str, object] = {}
    if args.projects_dirs:
        cli_overrides["hcl"] = {"projects_dirs": args.projects_dirs}

    from h3c_hcl_mcp.infrastructure.settings import load_settings

    settings = load_settings(
        cli_args=cli_overrides if cli_overrides else None,
        config_path=args.config,
    )

    from h3c_hcl_mcp.infrastructure.logging import setup_logging

    setup_logging(settings.server.log_level)
    print(f"{settings.server.name} v{VERSION} -- starting stdio server...", file=sys.stderr)

    server = create_server(settings=settings)
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
