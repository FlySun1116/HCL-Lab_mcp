"""Entry point for h3c-hcl-mcp: starts the MCP stdio server."""

import sys


def main() -> None:
    """Launch the HCL-Lab MCP Server via stdio transport."""
    print("h3c-hcl-mcp v0.0.1 — starting...", file=sys.stderr)
    # TODO: wire up real MCP server in Task T6 (Composition Root)
    print("Server placeholder: MCP stdio loop not yet implemented.", file=sys.stderr)


if __name__ == "__main__":
    main()
