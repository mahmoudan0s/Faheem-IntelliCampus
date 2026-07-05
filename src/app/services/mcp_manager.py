import logging
import os
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("uvicorn")

SERVER_SCRIPTS = {
    "pgvector": os.path.join(os.path.dirname(__file__), "..", "mcp_servers", "pgvector_server.py"),
    "sqlserver": os.path.join(os.path.dirname(__file__), "..", "mcp_servers", "sqlserver_server.py"),
}

WORK_DIR = os.path.join(os.path.dirname(__file__), "..", "..")


class MCPClientSession:
    def __init__(self, name: str):
        self.name = name
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()

    async def connect(self, script_path: str):
        params = StdioServerParameters(
            command=sys.executable or "python",
            args=[script_path],
            env={**os.environ, "PYTHONPATH": os.pathsep.join([WORK_DIR, os.environ.get("PYTHONPATH", "")])},
        )
        try:
            streams_ctx = stdio_client(params)
            read, write = await self._exit_stack.enter_async_context(streams_ctx)
            session_ctx = ClientSession(read, write)
            self._session = await self._exit_stack.enter_async_context(session_ctx)
            await self._session.initialize()
        except Exception:
            await self._exit_stack.aclose()
            raise
        logger.info("MCP connected: %s", self.name)

    async def list_tools(self):
        result = await self._session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict | None = None):
        return await self._session.call_tool(name, arguments or {})

    async def close(self):
        try:
            await self._exit_stack.aclose()
        except BaseException:
            pass
        logger.info("MCP disconnected: %s", self.name)


class MCPManager:
    def __init__(self):
        self._sessions: dict[str, MCPClientSession] = {}

    async def connect_all(self):
        for name, script_path in SERVER_SCRIPTS.items():
            try:
                session = MCPClientSession(name)
                await session.connect(script_path)
                self._sessions[name] = session
            except Exception as e:
                logger.error("Failed to connect MCP server '%s': %s", name, e)

    async def get_all_tools(self) -> list[dict]:
        tools = []
        for name, session in self._sessions.items():
            try:
                server_tools = await session.list_tools()
                for tool in server_tools:
                    tools.append({
                        "server": name,
                        "name": tool.name,
                        "description": tool.description or "",
                        "inputSchema": tool.inputSchema,
                    })
            except Exception as e:
                logger.error("Failed to list tools from %s: %s", name, e)
        return tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict | None = None):
        session = self._sessions.get(server_name)
        if not session:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await session.call_tool(tool_name, arguments)

    async def close_all(self):
        for name, session in list(self._sessions.items()):
            try:
                await session.close()
            except BaseException:
                pass
        self._sessions.clear()

    def tool_schemas_for_groq(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": f"{t['server']}__{t['name']}",
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in tools
        ]

    @staticmethod
    def parse_tool_name(full_name: str) -> tuple[str, str]:
        server, _, tool = full_name.partition("__")
        return server, tool
