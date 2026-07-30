import json
from types import SimpleNamespace

import pytest

from backend.core.mcp_client import McpToolRegistry

pytestmark = pytest.mark.asyncio


def _fake_tool(name, description="bir araç", read_only=None):
    # Alan adları gerçek `mcp` paketinin (pydantic) modelleriyle birebir aynı:
    # input_schema, read_only_hint (snake_case - MCP'nin JSON-RPC protokolü
    # camelCase olsa da Python SDK'sı öyle değil, bkz. mcp_client.py'deki not).
    annotations = None if read_only is None else SimpleNamespace(read_only_hint=read_only)
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
        annotations=annotations,
    )


class FakeSession:
    def __init__(self, tools, call_result=None, call_error=None):
        self._tools = tools
        self._call_result = call_result
        self._call_error = call_error
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if self._call_error:
            raise self._call_error
        return self._call_result


def _write_config(tmp_path, servers):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return path


async def test_connect_all_missing_config_leaves_tools_empty(tmp_path):
    registry = McpToolRegistry()
    await registry.connect_all(tmp_path / "does_not_exist.json")
    assert registry.all_declarations() == []


async def test_connect_all_corrupt_json_leaves_tools_empty(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text("bu geçerli bir json değil {{{", encoding="utf-8")
    registry = McpToolRegistry()
    await registry.connect_all(path)  # exception dışarı sızmamalı
    assert registry.all_declarations() == []


async def test_connect_all_non_object_top_level_json_leaves_tools_empty(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps(["bu bir liste, obje değil"]), encoding="utf-8")
    registry = McpToolRegistry()
    await registry.connect_all(path)  # AttributeError sızmamalı
    assert registry.all_declarations() == []


async def test_connect_all_mcpservers_not_object_leaves_tools_empty(tmp_path):
    config_path = _write_config(tmp_path, ["yanlış tip"])
    registry = McpToolRegistry()
    await registry.connect_all(config_path)
    assert registry.all_declarations() == []


async def test_connect_all_registers_tools_with_server_prefix(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": ["-y", "@github/mcp-server"]},
        "spotify": {"command": "npx", "args": ["-y", "spotify-mcp"]},
    })
    sessions = {
        "github": FakeSession([_fake_tool("list_repos", read_only=True)]),
        "spotify": FakeSession([_fake_tool("play", read_only=False)]),
    }

    async def fake_connect(server_id, server_cfg, exit_stack):
        return sessions[server_id]

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    assert registry.has("github__list_repos")
    assert registry.has("spotify__play")
    assert len(registry.all_declarations()) == 2


async def test_read_only_declarations_filters_correctly(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": []},
    })
    session = FakeSession([
        _fake_tool("list_repos", read_only=True),
        _fake_tool("delete_repo", read_only=False),
        _fake_tool("no_annotations", read_only=None),
    ])

    async def fake_connect(server_id, server_cfg, exit_stack):
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    read_only_names = {d.name for d in registry.read_only_declarations()}
    all_names = {d.name for d in registry.all_declarations()}
    assert read_only_names == {"github__list_repos"}
    assert all_names == {"github__list_repos", "github__delete_repo", "github__no_annotations"}


async def test_one_server_connect_failure_does_not_affect_other(tmp_path):
    config_path = _write_config(tmp_path, {
        "broken": {"command": "npx", "args": []},
        "github": {"command": "npx", "args": []},
    })
    session = FakeSession([_fake_tool("list_repos", read_only=True)])

    async def fake_connect(server_id, server_cfg, exit_stack):
        if server_id == "broken":
            raise RuntimeError("bağlantı reddedildi")
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    assert not registry.has("broken__anything")
    assert registry.has("github__list_repos")


async def test_has_and_is_read_only_unknown_name_return_false():
    registry = McpToolRegistry()
    assert registry.has("bilinmeyen__arac") is False
    assert registry.is_read_only("bilinmeyen__arac") is False


async def test_call_returns_text_from_content_blocks(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": []},
    })
    session = FakeSession(
        [_fake_tool("list_repos", read_only=True)],
        call_result=SimpleNamespace(content=[SimpleNamespace(text="sonuç")]),
    )

    async def fake_connect(server_id, server_cfg, exit_stack):
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    reply = await registry.call("github__list_repos", {"query": "x"})
    assert reply == "sonuç"
    assert session.calls == [("list_repos", {"query": "x"})]


async def test_call_unknown_tool_returns_message():
    registry = McpToolRegistry()
    reply = await registry.call("bilinmeyen__arac", {})
    assert "Bilinmeyen MCP aracı" in reply


async def test_same_tool_name_on_different_servers_does_not_collide(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": []},
        "spotify": {"command": "npx", "args": []},
    })
    sessions = {
        "github": FakeSession([_fake_tool("search", read_only=True)]),
        "spotify": FakeSession([_fake_tool("search", read_only=True)]),
    }

    async def fake_connect(server_id, server_cfg, exit_stack):
        return sessions[server_id]

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    assert registry.has("github__search")
    assert registry.has("spotify__search")
    assert len(registry.all_declarations()) == 2


async def test_call_joins_multiple_text_blocks_and_skips_non_text(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": []},
    })
    session = FakeSession(
        [_fake_tool("list_repos", read_only=True)],
        call_result=SimpleNamespace(content=[
            SimpleNamespace(text="birinci"),
            SimpleNamespace(),  # metin alanı olmayan (ör. görsel) blok - atlanmalı
            SimpleNamespace(text="ikinci"),
        ]),
    )

    async def fake_connect(server_id, server_cfg, exit_stack):
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    reply = await registry.call("github__list_repos", {})
    assert reply == "birinci\nikinci"


async def test_register_tools_matches_real_mcp_sdk_shape(tmp_path):
    """Sahte SimpleNamespace'lerin gerçek `mcp` paketinin pydantic modelleriyle
    (Tool/ToolAnnotations, snake_case alanlar) hâlâ uyumlu olduğunu doğrular.
    `mcp` kurulu değilse atlanır (opsiyonel bağımlılık, sadece bu testte gerçek
    paket gerekiyor - registry'nin geri kalanı hiçbir zaman gerçek mcp'ye
    ihtiyaç duymuyor, connect_fn her zaman enjekte edilebiliyor)."""
    mcp_types = pytest.importorskip("mcp.types")

    config_path = _write_config(tmp_path, {"github": {"command": "npx", "args": []}})
    real_tool = mcp_types.Tool(
        name="list_repos",
        description="Repoları listeler",
        input_schema={"type": "object", "properties": {}},
        annotations=mcp_types.ToolAnnotations(read_only_hint=True),
    )
    session = FakeSession([real_tool])

    async def fake_connect(server_id, server_cfg, exit_stack):
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    assert registry.has("github__list_repos")
    assert registry.is_read_only("github__list_repos")


async def test_call_empty_content_returns_placeholder(tmp_path):
    config_path = _write_config(tmp_path, {
        "github": {"command": "npx", "args": []},
    })
    session = FakeSession(
        [_fake_tool("list_repos", read_only=True)],
        call_result=SimpleNamespace(content=[]),
    )

    async def fake_connect(server_id, server_cfg, exit_stack):
        return session

    registry = McpToolRegistry()
    await registry.connect_all(config_path, connect_fn=fake_connect)

    reply = await registry.call("github__list_repos", {})
    assert reply == "(boş sonuç)"
