"""Telnet-based console transport implementing DeviceTransport.

Connects to HCL loopback Telnet consoles, handles IAC negotiation,
startup noise filtering, command execution with pagination handling,
and graceful disconnect.
"""

from __future__ import annotations

import asyncio
import time

from h3c_hcl_mcp.adapters.comware.base import (
    SessionState,
)
from h3c_hcl_mcp.adapters.comware.prompt import (
    detect_prompt,
    is_more_prompt,
)
from h3c_hcl_mcp.adapters.comware.session import DeviceSession
from h3c_hcl_mcp.domain.command import (
    CommandRequest,
    CommandResult,
    CommandType,
)
from h3c_hcl_mcp.domain.device import RuntimeEndpoint
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode
from h3c_hcl_mcp.ports.device_transport import DeviceTransport

# ---- Telnet IAC constants ----
_IAC = 0xFF
_WILL = 0xFB
_WONT = 0xFC
_DO = 0xFD
_DONT = 0xFE
_SB = 0xFA
_SE = 0xF0

# Default timeout for prompt detection after connect (seconds)
_DEFAULT_PROMPT_TIMEOUT = 15.0

# Buffer size for reads
_READ_CHUNK = 4096

# How long to poll for more data when buffer is quiet (seconds)
_IDLE_POLL_INTERVAL = 0.1


class ConsoleTelnetTransport(DeviceTransport):
    """Telnet-based console transport for Comware devices.

    Connects to an HCL loopback telnet console on 127.0.0.1,
    handles IAC negotiation, filters startup noise, and executes
    CLI commands with pagination handling.

    Each instance is bound to a single device session.
    """

    def __init__(self, session: DeviceSession) -> None:
        self._session = session
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._current_prompt: str | None = None
        self._connected = False

    # ---- DeviceTransport implementation ----

    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        """Establish a telnet connection and wait for CLI prompt.

        Args:
            endpoint: RuntimeEndpoint with host/port for the console.

        Raises:
            DomainError(CONNECTION_FAILED): TCP connection failed.
            DomainError(PROMPT_TIMEOUT): No CLI prompt received in time.
        """
        self._session.state = SessionState.CONNECTING

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(endpoint.host, endpoint.port),
                timeout=endpoint.confidence if endpoint.confidence > 0 else _DEFAULT_PROMPT_TIMEOUT,
            )
        except TimeoutError:
            self._session.state = SessionState.DISCONNECTED
            raise DomainError(
                ErrorCode.CONNECTION_FAILED,
                f"Connection to {endpoint.host}:{endpoint.port} timed out",
                {"host": endpoint.host, "port": endpoint.port},
            ) from None
        except OSError as exc:
            self._session.state = SessionState.DISCONNECTED
            raise DomainError(
                ErrorCode.CONNECTION_FAILED,
                f"Failed to connect to {endpoint.host}:{endpoint.port}: {exc}",
                {"host": endpoint.host, "port": endpoint.port},
            ) from exc

        self._connected = True

        try:
            await self._wait_for_prompt(timeout=_DEFAULT_PROMPT_TIMEOUT)
        except DomainError:
            self._session.state = SessionState.DISCONNECTED
            raise

        self._session.state = SessionState.READY
        self._session.reset_reconnect()

    async def execute(self, request: CommandRequest) -> CommandResult:
        """Execute a single CLI command and collect the output.

        Handles command echo, pagination (---- More ----), prompt detection,
        timeout, and output truncation.

        Args:
            request: The command request with target, command text, timeout, etc.

        Returns:
            CommandResult with raw output, detected prompt, duration, and warnings.

        Raises:
            DomainError(COMMAND_TIMEOUT): command did not complete.
            DomainError(CONNECTION_CLOSED): session was lost mid-command.
        """
        if not self._connected or self._writer is None or self._reader is None:
            raise DomainError(
                ErrorCode.CONNECTION_CLOSED,
                "Not connected to device",
                {"device_id": self._session.device_id},
            )

        if request.command_type in (CommandType.CONFIG, CommandType.SAVE, CommandType.RESET):
            raise DomainError(
                ErrorCode.WRITE_DISABLED,
                f"Command type {request.command_type.value} is write-disabled in v0.1",
                {"command_type": request.command_type.value},
            )

        async with self._session.lock:
            self._session.state = SessionState.BUSY
            self._session.touch()
            start = time.monotonic()
            warnings: list[str] = []

            try:
                # Send command
                self._writer.write((request.command + "\r\n").encode("ascii", errors="replace"))
                await self._writer.drain()

                # Collect output with pagination and timeout
                raw_output = await self._collect_output(
                    timeout=request.timeout_seconds,
                    max_chars=request.max_output_chars,
                    warnings=warnings,
                )
            except TimeoutError:
                duration = (time.monotonic() - start) * 1000
                self._session.state = SessionState.READY
                raise DomainError(
                    ErrorCode.COMMAND_TIMEOUT,
                    f"Command timed out after {request.timeout_seconds:.0f}s",
                    {
                        "command": request.command,
                        "device_id": self._session.device_id,
                        "duration_ms": duration,
                    },
                ) from None

            duration = (time.monotonic() - start) * 1000

            # Detect final prompt
            prompt = detect_prompt(raw_output)
            self._current_prompt = prompt

            truncated = len(raw_output) >= request.max_output_chars

            self._session.state = SessionState.READY

            return CommandResult(
                target=request.target,
                command=request.command,
                raw_output=raw_output,
                prompt_detected=prompt,
                duration_ms=round(duration, 1),
                truncated=truncated,
                warnings=warnings,
            )

    async def execute_config(self, commands: list[str], timeout_seconds: float = 30.0) -> CommandResult:
        """Configuration writes are disabled in v0.1.

        Always raises WRITE_DISABLED.
        """
        raise DomainError(
            ErrorCode.WRITE_DISABLED,
            "Configuration write operations are not available in v0.1",
            {"commands_count": len(commands)},
        )

    async def close(self) -> None:
        """Gracefully close the telnet session."""
        self._session.state = SessionState.CLOSING

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass

        self._reader = None
        self._writer = None
        self._connected = False
        self._current_prompt = None
        self._session.state = SessionState.DISCONNECTED

    # ---- Internal helpers ----

    async def _wait_for_prompt(self, timeout: float) -> None:
        """Read from the connection until a valid CLI prompt is detected.

        Filters telnet IAC commands and startup noise.
        Raises DomainError(PROMPT_TIMEOUT) if no prompt appears within timeout.
        """
        buffer = ""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(_READ_CHUNK) if self._reader else b"",
                    timeout=_IDLE_POLL_INTERVAL,
                )
            except TimeoutError:
                # Check existing buffer for a prompt
                prompt = detect_prompt(buffer)
                if prompt is not None:
                    self._current_prompt = prompt
                    return
                continue

            if not data:
                # Connection closed
                raise DomainError(
                    ErrorCode.CONNECTION_CLOSED,
                    "Connection closed while waiting for prompt",
                    {"device_id": self._session.device_id},
                )

            # Filter IAC sequences from the data stream
            clean = _filter_iac(data)
            if clean:
                buffer += clean.decode("ascii", errors="replace")

            prompt = detect_prompt(buffer)
            if prompt is not None:
                self._current_prompt = prompt
                return

        raise DomainError(
            ErrorCode.PROMPT_TIMEOUT,
            f"No CLI prompt detected within {timeout:.0f}s",
            {
                "device_id": self._session.device_id,
                "buffer_tail": buffer[-200:] if len(buffer) > 200 else buffer,
            },
        )

    async def _collect_output(
        self,
        timeout: float,
        max_chars: int,
        warnings: list[str],
    ) -> str:
        """Read command output from the device, handling pagination.

        Reads data until a non-More prompt is detected or timeout.
        Sends space on '---- More ----' to continue pagination.
        Truncates output at max_chars.
        """
        buffer = ""
        deadline = time.monotonic() + timeout
        more_pages_sent = 0

        while time.monotonic() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(_READ_CHUNK) if self._reader else b"",
                    timeout=_IDLE_POLL_INTERVAL,
                )
            except TimeoutError:
                # Check if we already have a final prompt
                prompt = detect_prompt(buffer)
                if prompt is not None and not is_more_prompt(buffer):
                    # Buffer looks complete — give it one more short poll
                    remaining = deadline - time.monotonic()
                    if remaining > 1.0:
                        try:
                            data = await asyncio.wait_for(
                                self._reader.read(_READ_CHUNK) if self._reader else b"",
                                timeout=min(1.0, remaining),
                            )
                            if data:
                                clean = _filter_iac(data)
                                if clean:
                                    buffer += clean.decode("ascii", errors="replace")
                                    continue
                        except TimeoutError:
                            pass
                    break
                continue

            if not data:
                break

            clean = _filter_iac(data)
            if clean:
                buffer += clean.decode("ascii", errors="replace")

            # Handle pagination
            if is_more_prompt(buffer):
                if self._writer is not None:
                    self._writer.write(b" \r\n")
                    await self._writer.drain()
                more_pages_sent += 1
                # Reset deadline extension for long paginated output
                deadline = max(deadline, time.monotonic() + (timeout * 0.5))

            # Check for final prompt
            prompt = detect_prompt(buffer)
            if prompt is not None and not is_more_prompt(buffer):
                # Brief pause to ensure output is complete
                remaining = deadline - time.monotonic()
                if remaining > 0.5:
                    try:
                        more_data = await asyncio.wait_for(
                            self._reader.read(_READ_CHUNK) if self._reader else b"",
                            timeout=min(0.3, remaining),
                        )
                        if more_data:
                            clean_more = _filter_iac(more_data)
                            if clean_more:
                                buffer += clean_more.decode("ascii", errors="replace")
                            continue
                    except TimeoutError:
                        pass
                break

            # Truncation check
            if len(buffer) >= max_chars:
                warnings.append(f"Output truncated at {max_chars} characters")
                break

        if more_pages_sent > 0:
            warnings.append(f"Paginated output: {more_pages_sent} page(s)")

        # Truncate to max chars if needed
        if len(buffer) > max_chars:
            buffer = buffer[:max_chars]

        return buffer


def _filter_iac(data: bytes) -> bytes:
    """Remove IAC telnet command sequences from a byte buffer.

    IAC sequences are 3 bytes: IAC <cmd> <option>
    Sub-negotiation: IAC SB <option> <data> IAC SE
    All IAC bytes inside the data stream (IAC IAC) become a single 0xFF.

    Returns the data portion only (non-IAC bytes).
    """
    if _IAC not in data:
        return data

    result = bytearray()
    i = 0
    n = len(data)

    while i < n:
        b = data[i]
        if b != _IAC:
            result.append(b)
            i += 1
            continue

        # Peek at next byte
        if i + 1 >= n:
            # IAC at end of buffer — discard (incomplete command)
            break

        cmd = data[i + 1]

        if cmd == _IAC:
            # Escaped IAC — literal 0xFF in data stream
            result.append(_IAC)
            i += 2
        elif cmd in (_WILL, _WONT, _DO, _DONT):
            # 3-byte command: IAC <cmd> <option>
            i += 3
        elif cmd == _SB:
            # Sub-negotiation: scan for IAC SE
            i += 2  # skip IAC SB
            while i + 1 < n:
                if data[i] == _IAC and data[i + 1] == _SE:
                    i += 2
                    break
                i += 1
            else:
                # Unterminated SB — skip rest
                i = n
        else:
            # Unknown IAC command — skip 2 bytes
            i += 2

    return bytes(result)


def _send_iac_response(writer: asyncio.StreamWriter, cmd: int, option: int) -> None:
    """Send an IAC response. Not currently used but available for negotiation."""
    writer.write(bytes([_IAC, cmd, option]))
