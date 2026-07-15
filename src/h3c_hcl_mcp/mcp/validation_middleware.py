"""Validation error middleware — maps FastMCP/Pydantic validation errors.

FastMCP validates tool arguments before the tool function runs.
Validation errors come through as ToolError with Pydantic messages.
This module intercepts these and reformats them to:
- MCP isError=true
- ErrorCode INVALID_ARGUMENT
- Field name and valid range/enum information
- request_id for audit correlation
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import FastMCP


def wrap_call_tool_with_validation(mcp: FastMCP) -> None:
    """Wrap server.call_tool to reformat validation errors.

    After calling this, validation errors will be reformatted to include
    INVALID_ARGUMENT error code, field names, and request_id.
    """
    original_call_tool = mcp.call_tool

    async def wrapped_call_tool(
        name: str,
        arguments: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        try:
            return await original_call_tool(name, arguments, **kwargs)
        except ToolError as e:
            msg = str(e)
            if "validation error" in msg.lower():
                # Reformat Pydantic validation error
                request_id = str(uuid.uuid4())
                field_errors = _parse_validation_errors(msg)
                reformatted = {
                    "error": {
                        "code": "INVALID_ARGUMENT",
                        "message": "Validation error",
                        "fields": field_errors,
                        "request_id": request_id,
                    }
                }
                raise ToolError(json.dumps(reformatted)) from e
            raise

    mcp.call_tool = wrapped_call_tool  # type: ignore[method-assign]


def _parse_validation_errors(msg: str) -> list[dict[str, str]]:
    """Parse Pydantic validation error message into structured field errors.

    Format: "Error executing tool X: N validation errors for XArguments
    field_name
      Error description [type=error_type, input_value='...']"

    Returns list of {"field": "...", "message": "...", "type": "..."}
    """
    errors: list[dict[str, str]] = []

    # Extract the validation part (after first colon-newline or after "Arguments")
    try:
        # Find start of actual errors
        lines = msg.split("\n")
        in_errors = False
        current_field = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if "validation error" in stripped.lower():
                in_errors = True
                continue
            if in_errors and not line.startswith(" ") and not line.startswith("\t"):
                if "[type=" in stripped:
                    # This is an error detail line for current field
                    type_start = stripped.find("[type=")
                    type_end = stripped.find(",", type_start) if type_start >= 0 else -1
                    err_type = ""
                    if type_start >= 0:
                        end = type_end if type_end > type_start else len(stripped)
                        err_type = stripped[type_start + 6 : end].rstrip("]")
                    errors.append(
                        {
                            "field": current_field,
                            "message": stripped[:type_start].strip() if type_start >= 0 else stripped,
                            "type": err_type,
                        }
                    )
                else:
                    current_field = stripped
    except Exception:
        # Fallback: return raw message as a single error
        errors.append({"field": "unknown", "message": msg[:200], "type": "validation_error"})

    if not errors:
        errors.append({"field": "unknown", "message": msg[:200], "type": "validation_error"})

    return errors
