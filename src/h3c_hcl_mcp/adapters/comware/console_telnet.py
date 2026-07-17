"""Telnet-based console transport implementing DeviceTransport.

Connects to HCL loopback Telnet consoles, handles IAC negotiation,
startup noise filtering, command execution with pagination handling,
and graceful disconnect.
"""

from __future__ import annotations

import asyncio
import ipaddress
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
from h3c_hcl_mcp.domain.device import RuntimeEndpoint, TransportType
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


def _is_loopback_host(host: str) -> bool:
    """Return whether a console host is local-only."""
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _TelnetIACFilter:
    """Incrementally remove Telnet negotiation across arbitrary TCP chunks."""

    _DATA = 0
    _IAC = 1
    _OPTION = 2
    _SUBNEGOTIATION = 3
    _SUBNEGOTIATION_IAC = 4

    def __init__(self) -> None:
        self._state = self._DATA

    def reset(self) -> None:
        self._state = self._DATA

    def feed(self, data: bytes) -> bytes:
        result = bytearray()
        for byte in data:
            if self._state == self._DATA:
                if byte == _IAC:
                    self._state = self._IAC
                else:
                    result.append(byte)
            elif self._state == self._IAC:
                if byte == _IAC:
                    result.append(_IAC)
                    self._state = self._DATA
                elif byte in {_WILL, _WONT, _DO, _DONT}:
                    self._state = self._OPTION
                elif byte == _SB:
                    self._state = self._SUBNEGOTIATION
                else:
                    self._state = self._DATA
            elif self._state == self._OPTION:
                self._state = self._DATA
            elif self._state == self._SUBNEGOTIATION:
                if byte == _IAC:
                    self._state = self._SUBNEGOTIATION_IAC
            elif self._state == self._SUBNEGOTIATION_IAC:
                if byte == _SE:
                    self._state = self._DATA
                else:
                    self._state = self._SUBNEGOTIATION
        return bytes(result)


class ConsoleTelnetTransport(DeviceTransport):
    """Telnet-based console transport for Comware devices.

    Connects to an HCL loopback telnet console on 127.0.0.1,
    handles IAC negotiation, filters startup noise, and executes
    CLI commands with pagination handling.

    Each instance is bound to a single device session.
    """

    def __init__(
        self,
        session: DeviceSession,
        connect_timeout_seconds: float = 5.0,
        prompt_timeout_seconds: float = _DEFAULT_PROMPT_TIMEOUT,
    ) -> None:
        self._session = session
        self._connect_timeout_seconds = max(0.1, connect_timeout_seconds)
        self._prompt_timeout_seconds = max(0.1, prompt_timeout_seconds)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._current_prompt: str | None = None
        self._connected = False
        self._iac_filter = _TelnetIACFilter()

    # ---- DeviceTransport implementation ----

    async def connect(self, endpoint: RuntimeEndpoint) -> None:
        """Establish a telnet connection and wait for CLI prompt.

        Args:
            endpoint: RuntimeEndpoint with host/port for the console.

        Raises:
            DomainError(CONNECTION_FAILED): TCP connection failed.
            DomainError(PROMPT_TIMEOUT): No CLI prompt received in time.
        """
        if endpoint.transport != TransportType.CONSOLE_TELNET:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Console Telnet transport cannot open a non-console endpoint",
            )
        if not _is_loopback_host(endpoint.host):
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Console Telnet endpoint must use a loopback host in v0.1",
            )

        self._session.state = SessionState.CONNECTING
        self._iac_filter.reset()

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(endpoint.host, endpoint.port),
                timeout=self._connect_timeout_seconds,
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
            await self._wait_for_prompt(timeout=self._prompt_timeout_seconds)
        except DomainError:
            await self.close()
            raise
        except OSError as exc:
            await self.close()
            raise DomainError(
                ErrorCode.CONNECTION_CLOSED,
                "Connection closed while waiting for the CLI prompt",
                {"device_id": self._session.device_id},
            ) from exc
        except asyncio.CancelledError:
            await self.close()
            raise

        self._session.state = SessionState.READY
        self._session.reset_reconnect()
        self._session.touch()

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
                    expected_prompt=self._current_prompt,
                )
            except TimeoutError:
                duration = (time.monotonic() - start) * 1000
                await self.close()
                raise DomainError(
                    ErrorCode.COMMAND_TIMEOUT,
                    f"Command timed out after {request.timeout_seconds:.0f}s",
                    {
                        "command": request.command,
                        "device_id": self._session.device_id,
                        "duration_ms": duration,
                    },
                ) from None
            except DomainError:
                await self.close()
                raise
            except OSError as exc:
                await self.close()
                raise DomainError(
                    ErrorCode.CONNECTION_CLOSED,
                    "Connection closed while executing the command",
                    {"device_id": self._session.device_id},
                ) from exc
            except asyncio.CancelledError:
                await self.close()
                raise

            duration = (time.monotonic() - start) * 1000

            # Detect final prompt
            prompt = detect_prompt(raw_output, expected_prompt=self._current_prompt)
            self._current_prompt = prompt

            truncated = len(raw_output) >= request.max_output_chars
            if prompt is None and not truncated:
                await self.close()
                raise DomainError(
                    ErrorCode.COMMAND_TIMEOUT,
                    f"Command timed out after {request.timeout_seconds:.0f}s",
                    {
                        "command": request.command,
                        "device_id": self._session.device_id,
                        "duration_ms": duration,
                    },
                )

            # A truncated stream or a peer that closed after the final prompt
            # cannot be safely reused: unread/late bytes could be mistaken for
            # the next command's response.
            peer_closed = self._reader is None or self._reader.at_eof()
            if truncated or peer_closed:
                await self.close()
            else:
                self._session.state = SessionState.READY

            self._session.command_count += 1
            self._session.touch()

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
        assert self._reader is not None, "reader must be set before calling _wait_for_prompt"
        buffer = ""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(_READ_CHUNK),
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
            clean = self._iac_filter.feed(data)
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
                "received_chars": len(buffer),
            },
        )

    async def _collect_output(
        self,
        timeout: float,
        max_chars: int,
        warnings: list[str],
        expected_prompt: str | None,
    ) -> str:
        """Read command output from the device, handling pagination.

        Reads data until a non-More prompt is detected or timeout.
        Sends space on '---- More ----' to continue pagination.
        Truncates output at max_chars.
        """
        assert self._reader is not None, "reader must be set before calling _collect_output"
        buffer = ""
        deadline = time.monotonic() + timeout
        more_pages_sent = 0

        while time.monotonic() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._reader.read(_READ_CHUNK),
                    timeout=_IDLE_POLL_INTERVAL,
                )
            except TimeoutError:
                # Check if we already have a final prompt
                prompt = detect_prompt(buffer, expected_prompt=expected_prompt)
                if prompt is not None and not is_more_prompt(buffer):
                    # Buffer looks complete — give it one more short poll
                    remaining = deadline - time.monotonic()
                    if remaining > 1.0:
                        try:
                            data = await asyncio.wait_for(
                                self._reader.read(_READ_CHUNK),
                                timeout=min(1.0, remaining),
                            )
                            if data:
                                clean = self._iac_filter.feed(data)
                                if clean:
                                    buffer += clean.decode("ascii", errors="replace")
                                    continue
                        except TimeoutError:
                            pass
                    break
                continue

            if not data:
                raise DomainError(
                    ErrorCode.CONNECTION_CLOSED,
                    "Connection closed before the command prompt was received",
                    {"device_id": self._session.device_id},
                )

            clean = self._iac_filter.feed(data)
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
            prompt = detect_prompt(buffer, expected_prompt=expected_prompt)
            if prompt is not None and not is_more_prompt(buffer):
                # Brief pause to ensure output is complete
                remaining = deadline - time.monotonic()
                if remaining > 0.5:
                    try:
                        more_data = await asyncio.wait_for(
                            self._reader.read(_READ_CHUNK),
                            timeout=min(0.3, remaining),
                        )
                        if more_data:
                            clean_more = self._iac_filter.feed(more_data)
                            if clean_more:
                                extra = clean_more.decode("ascii", errors="replace")
                                # If the extra data is only a prompt (server's
                                # response to pagination space), skip it —
                                # the output is already complete.
                                extra_prompt = detect_prompt(extra, expected_prompt=expected_prompt)
                                if extra_prompt and extra.strip() == extra_prompt:
                                    pass  # ignore redundant prompt
                                else:
                                    buffer += extra
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

        # Count More prompts in output even if we didn't send space
        # (data may have arrived all at once)
        more_occurrences = buffer.count("---- More ----")
        if more_occurrences > 0 and more_pages_sent == 0:
            warnings.append(f"Paginated output detected: {more_occurrences} More prompt(s)")

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
    return _TelnetIACFilter().feed(data)


def _send_iac_response(writer: asyncio.StreamWriter, cmd: int, option: int) -> None:
    """Send an IAC response. Not currently used but available for negotiation."""
    writer.write(bytes([_IAC, cmd, option]))
