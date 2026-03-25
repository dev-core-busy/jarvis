"""MCP Client Manager – Verbindet Jarvis mit externen MCP-Tool-Servern."""

import asyncio
import json
import os
import uuid
from contextlib import AsyncExitStack
from typing import Any

from backend.tools.base import BaseTool
from backend.config import config

# ─── MCP Remote Tool Wrapper ────────────────────────────────────────────────

class McpRemoteTool(BaseTool):
    """Wraps ein MCP-Tool als Jarvis BaseTool."""

    def __init__(self, server_name: str, tool_info: dict, session: Any):
        self._server_name = server_name
        self._tool_name = tool_info.get("name", "unknown")
        self._description = tool_info.get("description", "MCP Tool")
        self._input_schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
        self._session = session

    @property
    def name(self) -> str:
        safe_server = self._server_name.replace("-", "_").replace(" ", "_")
        safe_tool = self._tool_name.replace("-", "_").replace(" ", "_")
        return f"mcp_{safe_server}_{safe_tool}"

    @property
    def description(self) -> str:
        return f"[MCP:{self._server_name}] {self._description}"

    def parameters_schema(self) -> dict:
        return self._input_schema

    async def execute(self, **kwargs) -> str:
        try:
            result = await self._session.call_tool(self._tool_name, kwargs)
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
                elif hasattr(content, "data"):
                    texts.append(f"[Binary: {len(content.data)} bytes]")
            return "\n".join(texts) if texts else "Tool ausgefuehrt (keine Textausgabe)"
        except Exception as e:
            return f"❌ MCP-Tool Fehler ({self._server_name}/{self._tool_name}): {e}"


# ─── Server Connection ───────────────────────────────────────────────────────

class McpServerConnection:
    """Verwaltet eine einzelne MCP-Server-Verbindung."""

    def __init__(self, server_config: dict):
        self.config = server_config
        self.id = server_config.get("id", str(uuid.uuid4()))
        self.name = server_config.get("name", "unknown")
        self.connected = False
        self.error: str | None = None
        self.tools: list[McpRemoteTool] = []
        self._session = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self):
        """Verbindet mit dem MCP-Server."""
        transport_type = self.config.get("transport", "stdio")
        try:
            from mcp import ClientSession
            self._exit_stack = AsyncExitStack()

            if transport_type == "stdio":
                await self._connect_stdio()
            elif transport_type in ("sse", "http"):
                await self._connect_sse()
            else:
                self.error = f"Unbekannter Transport: {transport_type}"
                return

            # Tools entdecken
            tools_response = await self._session.list_tools()
            self.tools = []
            for tool in tools_response.tools:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {"type": "object", "properties": {}},
                }
                self.tools.append(McpRemoteTool(self.name, tool_info, self._session))

            self.connected = True
            self.error = None
            print(f"[MCP] {self.name}: Verbunden, {len(self.tools)} Tools entdeckt", flush=True)

        except ImportError:
            self.error = "mcp-Paket nicht installiert (pip install mcp)"
            print(f"[MCP] {self.name}: {self.error}", flush=True)
        except Exception as e:
            self.error = str(e)
            self.connected = False
            print(f"[MCP] {self.name}: Verbindungsfehler – {e}", flush=True)

    async def _connect_stdio(self):
        """Stdio-Transport (Subprozess)."""
        from mcp import ClientSession
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        cmd = self.config.get("command", "")
        args = self.config.get("args", [])
        env_vars = self.config.get("env", {})

        # Umgebungsvariablen: System-ENV + benutzerdefinierte
        env = {**os.environ, **env_vars}

        server_params = StdioServerParameters(
            command=cmd,
            args=args,
            env=env,
        )

        transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def _connect_sse(self):
        """SSE/HTTP-Transport."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        url = self.config.get("url", "")
        transport = await self._exit_stack.enter_async_context(sse_client(url=url))
        read_stream, write_stream = transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def disconnect(self):
        """Trennt die Verbindung."""
        try:
            if self._exit_stack:
                await self._exit_stack.aclose()
        except Exception as e:
            print(f"[MCP] {self.name}: Fehler beim Trennen – {e}", flush=True)
        finally:
            self._session = None
            self._exit_stack = None
            self.connected = False
            self.tools = []

    def get_status(self) -> dict:
        """Status fuer Frontend."""
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.config.get("transport", "stdio"),
            "connected": self.connected,
            "error": self.error,
            "tool_count": len(self.tools),
            "tools": [{"name": t._tool_name, "description": t._description} for t in self.tools],
            "enabled": self.config.get("enabled", True),
        }


# ─── MCP Client Manager (Singleton) ─────────────────────────────────────────

class McpClientManager:
    """Verwaltet alle MCP-Server-Verbindungen."""

    def __init__(self):
        self._connections: dict[str, McpServerConnection] = {}

    async def connect_all(self):
        """Verbindet alle aktivierten MCP-Server aus der Konfiguration."""
        servers = config.get_mcp_servers()
        for srv in servers:
            if srv.get("enabled", True):
                await self.connect_server(srv["id"])

    async def connect_server(self, server_id: str) -> bool:
        """Verbindet einen einzelnen Server."""
        # Vorherige Verbindung trennen
        if server_id in self._connections:
            await self._connections[server_id].disconnect()

        servers = config.get_mcp_servers()
        srv_config = next((s for s in servers if s["id"] == server_id), None)
        if not srv_config:
            return False

        conn = McpServerConnection(srv_config)
        self._connections[server_id] = conn
        await conn.connect()
        return conn.connected

    async def disconnect_server(self, server_id: str):
        """Trennt einen einzelnen Server."""
        if server_id in self._connections:
            await self._connections[server_id].disconnect()
            del self._connections[server_id]

    async def disconnect_all(self):
        """Trennt alle Server (Shutdown)."""
        for conn in list(self._connections.values()):
            await conn.disconnect()
        self._connections.clear()

    def get_all_tools(self) -> list[BaseTool]:
        """Gibt alle Tools aller verbundenen Server zurueck."""
        tools = []
        for conn in self._connections.values():
            if conn.connected:
                tools.extend(conn.tools)
        return tools

    def get_status(self) -> list[dict]:
        """Status aller Server fuer Frontend."""
        servers = config.get_mcp_servers()
        result = []
        for srv in servers:
            sid = srv["id"]
            if sid in self._connections:
                result.append(self._connections[sid].get_status())
            else:
                result.append({
                    "id": sid,
                    "name": srv.get("name", "?"),
                    "transport": srv.get("transport", "stdio"),
                    "connected": False,
                    "error": None,
                    "tool_count": 0,
                    "tools": [],
                    "enabled": srv.get("enabled", True),
                })
        return result


# Singleton
mcp_manager = McpClientManager()
