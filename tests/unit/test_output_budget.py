"""Tests for the final MCP CallToolResult byte budget."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from h3c_hcl_mcp.domain.errors import ErrorCode
from h3c_hcl_mcp.domain.result import ToolResult
from h3c_hcl_mcp.mcp.output_budget import (
    bounded_error_payload,
    call_tool_result_bytes,
    compact_converted_result,
    compact_json,
    tool_result_bytes,
    with_output_budget,
)


def _tool_error_payload(error: ToolError) -> dict[str, object]:
    message = str(error)
    return json.loads(message[message.index("{") :])


def test_compact_conversion_keeps_text_and_structured_content_equivalent() -> None:
    result = ToolResult.success(request_id="req-compact", data={"status": "健康", "emoji": "✅"})
    structured = result.model_dump(mode="json")

    content, converted = compact_converted_result(
        ([TextContent(type="text", text=json.dumps(structured, indent=2))], structured),
        max_bytes=4096,
    )

    assert converted == structured
    assert len(content) == 1
    assert json.loads(content[0].text) == structured
    assert "\n" not in content[0].text


def test_tool_result_size_counts_utf8_bytes_and_both_mcp_channels() -> None:
    ascii_result = ToolResult.success(request_id="req-ascii", data={"value": "a" * 20})
    unicode_result = ToolResult.success(request_id="req-unicode", data={"value": "中" * 20})

    assert tool_result_bytes(unicode_result) > tool_result_bytes(ascii_result)

    content = [TextContent(type="text", text=compact_json(unicode_result.model_dump(mode="json")))]
    call_result = CallToolResult(
        content=content,
        structuredContent=unicode_result.model_dump(mode="json"),
        isError=False,
    )
    assert tool_result_bytes(unicode_result) == call_tool_result_bytes(call_result)


@pytest.mark.asyncio
async def test_tool_wrapper_rejects_oversized_result_with_stable_error() -> None:
    result = ToolResult.success(
        request_id="req-large",
        data={"device_output": "中文😀" * 1000},
        content_trust="untrusted_device_output",
    )

    @with_output_budget(1024)
    async def oversized_tool() -> ToolResult:
        return result

    with pytest.raises(ToolError) as exc_info:
        await oversized_tool()

    payload = _tool_error_payload(exc_info.value)
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.OUTPUT_TOO_LARGE.value
    assert error["request_id"] == "req-large"
    assert error["actual_bytes"] == tool_result_bytes(result)


def test_bounded_error_preserves_code_and_request_id() -> None:
    payload = {
        "error": {
            "code": ErrorCode.INVALID_ARGUMENT.value,
            "message": "错误" * 5000,
            "request_id": "req-error",
            "details": {"untrusted": "值" * 5000},
        }
    }

    bounded = bounded_error_payload(payload, max_bytes=1024)
    content = [TextContent(type="text", text=compact_json(bounded))]
    result = CallToolResult(content=content, isError=True)

    assert call_tool_result_bytes(result) <= 1024
    assert bounded["error"]["code"] == ErrorCode.INVALID_ARGUMENT.value
    assert bounded["error"]["request_id"] == "req-error"
    assert bounded["error"]["truncated"] is True
