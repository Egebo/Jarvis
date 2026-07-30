"""
Jarvis'i genel bir MCP host'una çevirir: config'te tanımlı MCP server'lara
bağlanır, araçlarını keşfeder, Gemini function-calling şemasına çevirir.
Çalıştırma mevcut manuel tool_executor akışına (SkillExecutor) bağlanır -
SDK'nın otomatik MCP çalıştırmasına GÜVENİLMEZ (hafıza kaydı + onay kapısı
bypass olur).
Spec: docs/superpowers/specs/2026-07-31-mcp-baglanti-design.md
"""
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path

log = logging.getLogger("jarvis")


class McpToolRegistry:
    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._tools: dict[str, dict] = {}

    async def connect_all(self, config_path: Path, connect_fn=None):
        """config_path yoksa/bozuksa sessizce boş kalır - MCP olmadan Jarvis
        normal çalışmaya devam eder. Her server kendi try/except'i içinde;
        biri başarısız olursa diğerleri etkilenmez."""
        connect = connect_fn or self._real_connect
        if not config_path.exists():
            return
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"MCP config okunamadı: {e}")
            return

        servers = config.get("mcpServers", {}) if isinstance(config, dict) else {}
        if not isinstance(servers, dict):
            log.warning("MCP config'te 'mcpServers' bir obje olmalı, atlanıyor")
            servers = {}

        for server_id, server_cfg in servers.items():
            try:
                session = await connect(server_id, server_cfg, self._exit_stack)
                await self._register_tools(server_id, session)
                log.info(f"🔌 MCP server bağlandı: {server_id}")
            except Exception as e:
                log.warning(f"MCP server '{server_id}' bağlanamadı: {e}")

    async def _real_connect(self, server_id: str, server_cfg: dict, exit_stack: AsyncExitStack):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )
        read, write = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _register_tools(self, server_id: str, session):
        from google.genai import types

        result = await session.list_tools()
        for tool in result.tools:
            exposed_name = f"{server_id}__{tool.name}"
            read_only = bool(getattr(tool.annotations, "readOnlyHint", False)) if tool.annotations else False
            self._tools[exposed_name] = {
                "session": session,
                "real_name": tool.name,
                "read_only": read_only,
                "declaration": types.FunctionDeclaration(
                    name=exposed_name,
                    description=tool.description or f"{server_id}: {tool.name}",
                    parameters_json_schema=tool.inputSchema or {"type": "object", "properties": {}},
                ),
            }

    def has(self, name: str) -> bool:
        return name in self._tools

    def is_read_only(self, name: str) -> bool:
        entry = self._tools.get(name)
        return bool(entry and entry["read_only"])

    def read_only_declarations(self) -> list:
        return [t["declaration"] for t in self._tools.values() if t["read_only"]]

    def all_declarations(self) -> list:
        return [t["declaration"] for t in self._tools.values()]

    async def call(self, name: str, args: dict) -> str:
        entry = self._tools.get(name)
        if entry is None:
            return f"Bilinmeyen MCP aracı: {name}"
        result = await entry["session"].call_tool(entry["real_name"], arguments=args)
        texts = [getattr(block, "text", None) for block in (result.content or [])]
        texts = [t for t in texts if t]
        return "\n".join(texts) if texts else "(boş sonuç)"

    async def close(self):
        await self._exit_stack.aclose()
