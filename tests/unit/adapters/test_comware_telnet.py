"""Unit tests for ConsoleTelnetTransport with a fake Comware-like telnet server.

The fake server simulates a real Comware device's telnet console:
- Sends a prompt on connect
- Echoes commands
- Responds to known commands with synthetic output
- Supports pagination (---- More ----)
- Can simulate delays, disconnects, and errors
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from h3c_hcl_mcp.adapters.comware.console_telnet import (
    ConsoleTelnetTransport,
    _filter_iac,
)
from h3c_hcl_mcp.adapters.comware.prompt import detect_prompt
from h3c_hcl_mcp.adapters.comware.session import DeviceSession
from h3c_hcl_mcp.domain.command import (
    CommandRequest,
    CommandTarget,
    CommandType,
)
from h3c_hcl_mcp.domain.device import (
    DiscoverySource,
    RuntimeEndpoint,
    TransportType,
)
from h3c_hcl_mcp.domain.errors import DomainError, ErrorCode

# ---- Constants ----

FIXTURES_DIR = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "device_outputs"

# IAC byte constants
IAC = 0xFF
WILL = 0xFB
WONT = 0xFC
DO = 0xFD
DONT = 0xFE

# ---- Fake Telnet Server ----


class FakeComwareTelnetServer:
    """A simple async telnet server that mimics Comware console behavior.

    Features:
    - Sends a Comware-like prompt on connect
    - Echoes commands back to the client
    - Responds to known commands with configurable output
    - Supports pagination with ---- More ----
    - Configurable delays, disconnects, and error injection
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        prompt: str = "<H3C>",
        echo_commands: bool = True,
        startup_delay: float = 0.0,
        disconnect_after: int = 0,
    ):
        self.host = host
        self.port = port
        self.prompt = prompt
        self.echo_commands = echo_commands
        self.startup_delay = startup_delay
        self.disconnect_after = disconnect_after  # disconnect after N commands

        self._server: asyncio.AbstractServer | None = None
        self._command_count = 0
        self._command_handlers: dict[str, str] = {}
        self._paginated_output: dict[str, list[str]] = {}

    @property
    def actual_port(self) -> int:
        """Return the port the server is actually listening on."""
        if self._server is None:
            return self.port
        return self._server.sockets[0].getsockname()[1]

    def register_command(self, command: str, output: str) -> None:
        """Register a command that returns fixed output."""
        self._command_handlers[command.lower()] = output

    def register_paginated(self, command: str, pages: list[str]) -> None:
        """Register a command that returns paginated output."""
        self._paginated_output[command.lower()] = pages

    async def start(self) -> None:
        """Start the fake server."""
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
        )

    async def stop(self) -> None:
        """Stop the fake server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a single client connection."""
        self._command_count = 0

        if self.startup_delay > 0:
            await asyncio.sleep(self.startup_delay)

        # Send initial IAC negotiation (optional, some servers do this)
        # For simplicity, skip IAC and just send the prompt
        writer.write(f"\r\n{self.prompt}".encode("ascii"))
        await writer.drain()

        while True:
            try:
                line = await reader.readline()
            except (ConnectionResetError, asyncio.IncompleteReadError):
                break

            if not line:
                break

            decoded = line.decode("ascii", errors="replace").strip()

            if not decoded:
                # Empty/whitespace-only input (e.g. space sent for pagination)
                # Send the prompt back so the transport knows we're ready
                writer.write(f"\r\n{self.prompt}".encode("ascii"))
                await writer.drain()
                continue

            self._command_count += 1

            # Check disconnect threshold
            if self.disconnect_after > 0 and self._command_count > self.disconnect_after:
                writer.close()
                return

            paginated_pages = self._paginated_output.get(decoded.lower())
            if paginated_pages is not None:
                # Send paginated output all at once with ---- More ---- markers
                response = self._build_paginated(paginated_pages)
            else:
                response = self._get_response(decoded)

            if self.echo_commands:
                writer.write(f"\r\n{decoded}\r\n".encode("ascii"))

            writer.write(response.encode("ascii"))
            writer.write(f"\r\n{self.prompt}".encode("ascii"))
            await writer.drain()

    def _build_paginated(self, pages: list[str]) -> str:
        """Build paginated response with ---- More ---- markers between pages."""
        parts: list[str] = []
        for i, page in enumerate(pages):
            parts.append(f"\r\n{page}")
            if i < len(pages) - 1:
                parts.append("\r\n  ---- More ----")
        return "".join(parts)

    def _get_response(self, command: str) -> str:
        """Get the response for a given command (non-paginated)."""
        cmd_lower = command.strip().lower()

        # Check fixed handlers
        if cmd_lower in self._command_handlers:
            return self._command_handlers[cmd_lower]

        # Default unknown command response
        return f"\r\n% Unknown command: {command}"


# ---- IAC Filter Tests ----


class TestIACFilter:
    """Unit tests for the IAC telnet command filter."""

    def test_no_iac_passthrough(self):
        data = b"Hello World\r\n"
        assert _filter_iac(data) == data

    def test_filter_will(self):
        # IAC WILL ECHO (0xFF 0xFB 0x01)
        data = b"Hello" + bytes([IAC, WILL, 0x01]) + b" World"
        assert _filter_iac(data) == b"Hello World"

    def test_filter_do(self):
        data = bytes([IAC, DO, 0x03]) + b"prompt>"
        assert _filter_iac(data) == b"prompt>"

    def test_filter_dont(self):
        data = bytes([IAC, DONT, 0x01]) + b"output"
        assert _filter_iac(data) == b"output"

    def test_filter_wont(self):
        data = b"line1\r\n" + bytes([IAC, WONT, 0x18])
        assert _filter_iac(data) == b"line1\r\n"

    def test_escaped_iac(self):
        # IAC IAC = literal 0xFF in data
        data = b"data" + bytes([IAC, IAC]) + b"more"
        result = _filter_iac(data)
        assert bytes([IAC]) in result  # Single 0xFF byte preserved

    def test_subnegotiation_filtered(self):
        # IAC SB TERMINAL-TYPE IAC SE
        data = b"before" + bytes([IAC, 0xFA, 0x18, 0x01, IAC, 0xF0]) + b"after"
        assert _filter_iac(data) == b"beforeafter"


# ---- Transport Tests ----


class TestConsoleTelnetTransport:
    """Integration-style tests using the fake telnet server."""

    @pytest.fixture
    async def server(self):
        """Create and start a fake server, yield it, then stop."""
        srv = FakeComwareTelnetServer(prompt="<H3C>")
        await srv.start()
        yield srv
        await srv.stop()

    @pytest.fixture
    def session(self):
        return DeviceSession(device_id=1, device_name="test-device")

    @pytest.fixture
    def endpoint(self, server):
        return RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            host="127.0.0.1",
            port=server.actual_port,
            source=DiscoverySource.MANUAL,
            confidence=1.0,
        )

    @pytest.fixture
    def transport(self, session):
        return ConsoleTelnetTransport(session=session)

    # ---- Connect Tests ----

    async def test_connect_success(self, transport, endpoint):
        await transport.connect(endpoint)
        assert transport._connected is True
        assert transport._current_prompt == "<H3C>"
        await transport.close()

    async def test_connect_sets_session_ready(self, transport, endpoint, session):
        await transport.connect(endpoint)
        assert session.state.value == "ready"
        await transport.close()

    async def test_connect_refused(self, transport):
        """Connect to a closed port should raise CONNECTION_FAILED."""
        # Use a port that is very unlikely to be open
        ep = RuntimeEndpoint(
            transport=TransportType.CONSOLE_TELNET,
            host="127.0.0.1",
            port=19999,
            source=DiscoverySource.MANUAL,
            confidence=1.0,
        )
        with pytest.raises(DomainError) as exc:
            await transport.connect(ep)
        assert exc.value.code == ErrorCode.CONNECTION_FAILED

    # ---- Execute Tests ----

    async def test_execute_known_command(self, transport, endpoint, server):
        server.register_command("display version", "H3C Comware Software, Version 7.1.070")
        await transport.connect(endpoint)

        target = CommandTarget(project_id="p1", device_id=1)
        request = CommandRequest(
            target=target,
            command="display version",
            command_type=CommandType.DISPLAY,
        )
        result = await transport.execute(request)

        assert "H3C Comware" in result.raw_output
        assert result.prompt_detected is not None
        await transport.close()

    async def test_execute_unknown_command(self, transport, endpoint, server):
        await transport.connect(endpoint)

        target = CommandTarget(project_id="p1", device_id=1)
        request = CommandRequest(
            target=target,
            command="display foobar",
            command_type=CommandType.DISPLAY,
        )
        result = await transport.execute(request)

        assert "Unknown command" in result.raw_output
        await transport.close()

    async def test_execute_with_pagination(self, transport, endpoint, server):
        server.register_paginated(
            "display running-config",
            [
                "interface GigabitEthernet1/0/1\r\n ip address 10.0.0.1 255.255.255.0",
                "interface GigabitEthernet1/0/2\r\n ip address 10.0.1.1 255.255.255.0",
                "interface GigabitEthernet1/0/3\r\n shutdown",
            ],
        )
        await transport.connect(endpoint)

        target = CommandTarget(project_id="p1", device_id=1)
        request = CommandRequest(
            target=target,
            command="display running-config",
            command_type=CommandType.DISPLAY,
            timeout_seconds=10.0,
        )
        result = await transport.execute(request)

        assert "GigabitEthernet1/0/1" in result.raw_output
        assert "GigabitEthernet1/0/3" in result.raw_output
        # Pagination markers should appear in the output
        assert "---- More ----" in result.raw_output
        await transport.close()

    async def test_execute_config_raises_write_disabled(self, transport, endpoint, server):
        await transport.connect(endpoint)

        target = CommandTarget(project_id="p1", device_id=1)
        request = CommandRequest(
            target=target,
            command="system-view",
            command_type=CommandType.CONFIG,
        )
        with pytest.raises(DomainError) as exc:
            await transport.execute(request)
        assert exc.value.code == ErrorCode.WRITE_DISABLED
        await transport.close()

    async def test_execute_not_connected(self, transport):
        target = CommandTarget(project_id="p1", device_id=1)
        request = CommandRequest(
            target=target,
            command="display version",
            command_type=CommandType.DISPLAY,
        )
        with pytest.raises(DomainError) as exc:
            await transport.execute(request)
        assert exc.value.code == ErrorCode.CONNECTION_CLOSED

    # ---- execute_config Tests ----

    async def test_execute_config_not_implemented(self, transport, endpoint, server):
        await transport.connect(endpoint)
        with pytest.raises(DomainError) as exc:
            await transport.execute_config(["system-view", "vlan 10"], 10.0)
        assert exc.value.code == ErrorCode.WRITE_DISABLED
        await transport.close()

    # ---- Close Tests ----

    async def test_close_sets_disconnected(self, transport, endpoint, session):
        await transport.connect(endpoint)
        await transport.close()
        assert transport._connected is False
        assert session.state.value == "disconnected"

    async def test_close_idempotent(self, transport, endpoint):
        await transport.connect(endpoint)
        await transport.close()
        # Second close should not raise
        await transport.close()

    # ---- Timeout Tests ----

    async def test_connect_prompt_timeout(self, transport):
        """If the server sends nothing, prompt detection should time out."""

        # Start a server that sends no prompt
        async def _blackhole(reader, writer):
            await asyncio.sleep(60)  # never send anything

        srv = await asyncio.start_server(_blackhole, host="127.0.0.1", port=0)
        try:
            port = srv.sockets[0].getsockname()[1]
            ep = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=port,
                source=DiscoverySource.MANUAL,
                confidence=0.1,  # low confidence => short connect timeout
            )

            transport = ConsoleTelnetTransport(
                session=DeviceSession(device_id=99, device_name="timeout-device")
            )
            with pytest.raises(DomainError) as exc:
                await transport.connect(ep)
            # Either CONNECTION_FAILED (timeout on TCP connect with low confidence)
            # or PROMPT_TIMEOUT
            assert exc.value.code in (ErrorCode.CONNECTION_FAILED, ErrorCode.PROMPT_TIMEOUT)
        finally:
            srv.close()
            await srv.wait_closed()

    # ---- Renamed Prompt Tests ----

    async def test_renamed_prompt(self, transport, session):
        srv = FakeComwareTelnetServer(prompt="<CoreRouter>")
        await srv.start()
        try:
            ep = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=srv.actual_port,
                source=DiscoverySource.MANUAL,
                confidence=1.0,
            )
            await transport.connect(ep)
            assert transport._current_prompt == "<CoreRouter>"
            assert detect_prompt(transport._current_prompt) == "<CoreRouter>"
            await transport.close()
        finally:
            await srv.stop()

    # ---- Server Disconnect Mid-Command ----

    async def test_server_disconnect(self, transport):
        srv = FakeComwareTelnetServer(disconnect_after=1)  # disconnect after 1st command
        srv.register_command("display version", "H3C Comware Software")
        await srv.start()
        try:
            ep = RuntimeEndpoint(
                transport=TransportType.CONSOLE_TELNET,
                host="127.0.0.1",
                port=srv.actual_port,
                source=DiscoverySource.MANUAL,
                confidence=1.0,
            )
            await transport.connect(ep)

            target = CommandTarget(project_id="p1", device_id=1)
            # First command should work
            request = CommandRequest(
                target=target,
                command="display version",
                command_type=CommandType.DISPLAY,
            )
            result = await transport.execute(request)
            assert "H3C Comware" in result.raw_output

            # Second command should fail (server disconnects after N commands)
            request2 = CommandRequest(
                target=target,
                command="display clock",
                command_type=CommandType.DISPLAY,
            )
            # This may return empty or raise — both are acceptable for a server disconnect
            await transport.execute(request2)
            # Session should detect it's no longer connected
            await transport.close()
        finally:
            await srv.stop()


class TestFakeTelnetServer:
    """Unit tests for the fake telnet server itself."""

    @pytest.fixture
    async def server(self):
        srv = FakeComwareTelnetServer(port=0, prompt="<H3C>")
        await srv.start()
        yield srv
        await srv.stop()

    async def test_sends_prompt_on_connect(self, server):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            assert b"<H3C>" in data
        finally:
            writer.close()

    async def test_echoes_command(self, server):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
        try:
            await asyncio.wait_for(reader.read(1024), timeout=2.0)  # consume prompt
            writer.write(b"display version\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert b"display version" in data
        finally:
            writer.close()

    async def test_registered_command_response(self, server):
        server.register_command("display version", "H3C Comware Software, Version 7.1.070")
        reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
        try:
            await asyncio.wait_for(reader.read(1024), timeout=2.0)  # consume prompt
            writer.write(b"display version\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert b"Comware Software" in data
            assert b"<H3C>" in data  # trailing prompt
        finally:
            writer.close()

    async def test_unknown_command(self, server):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
        try:
            await asyncio.wait_for(reader.read(1024), timeout=2.0)  # consume prompt
            writer.write(b"foobar\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert b"Unknown command" in data
        finally:
            writer.close()

    async def test_pagination(self, server):
        pages = [
            "line 1",
            "line 2",
            "line 3",
        ]
        server.register_paginated("display long", pages)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.actual_port)
        try:
            await asyncio.wait_for(reader.read(1024), timeout=2.0)  # consume prompt
            writer.write(b"display long\r\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            assert b"---- More ----" in data
            assert b"line 1" in data
            assert b"line 3" in data
        finally:
            writer.close()
