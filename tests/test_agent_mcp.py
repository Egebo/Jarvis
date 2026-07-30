import pytest
from backend.core.agent import TaskAgent
from backend.skills.file_tools import FileTools

pytestmark = pytest.mark.asyncio


class FakeMcpRegistry:
    def __init__(self, has=True, read_only=False, call_result="mcp sonuç",
                 declarations=None):
        self._has = has
        self._read_only = read_only
        self._call_result = call_result
        self._declarations = declarations or []
        self.call_calls = []

    def has(self, name):
        return self._has

    def is_read_only(self, name):
        return self._read_only

    def all_declarations(self):
        return self._declarations

    async def call(self, name, args):
        self.call_calls.append((name, args))
        return self._call_result


async def test_mcp_tool_not_read_only_asks_approval(tmp_path):
    registry = FakeMcpRegistry(has=True, read_only=False)
    asked = []

    async def approval_cb(desc):
        asked.append(desc)
        return True

    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=approval_cb, mcp_registry=registry)
    out = await agent._exec_tool("github__create_issue", {"title": "x"})
    assert len(asked) == 1 and "github__create_issue" in asked[0]
    assert registry.call_calls == [("github__create_issue", {"title": "x"})]
    assert out == "mcp sonuç"


async def test_mcp_tool_rejected_never_calls_mcp(tmp_path):
    registry = FakeMcpRegistry(has=True, read_only=False)

    async def approval_cb(desc):
        return False

    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=approval_cb, mcp_registry=registry)
    out = await agent._exec_tool("github__create_issue", {"title": "x"})
    assert out == "Kullanıcı bu adımı REDDETTİ. Adımı atla, işi elindekiyle sürdür."
    assert registry.call_calls == []


async def test_mcp_tool_read_only_skips_approval(tmp_path):
    registry = FakeMcpRegistry(has=True, read_only=True)
    asked = []

    async def approval_cb(desc):
        asked.append(desc)
        return True

    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=approval_cb, mcp_registry=registry)
    out = await agent._exec_tool("calendar__list_events", {})
    assert asked == []
    assert registry.call_calls == [("calendar__list_events", {})]
    assert out == "mcp sonuç"


async def test_no_mcp_registry_builtin_tools_unchanged(tmp_path):
    ft = FileTools(tmp_path)

    async def approve_all(desc):
        return True

    agent = TaskAgent("iş", ft, executor=None,
                      approval_cb=approve_all, mcp_registry=None)
    out = await agent._exec_tool("write_file", {"path": "a.txt", "content": "merhaba"})
    assert out.startswith("Yazıldı") or (tmp_path / "a.txt").read_text(encoding="utf-8") == "merhaba"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "merhaba"

    out2 = await agent._exec_tool("bilinmeyen_arac", {})
    assert out2 == "Bilinmeyen araç: bilinmeyen_arac"


async def test_declarations_include_mcp_ones(tmp_path):
    fake_decl_1 = object()
    fake_decl_2 = object()
    registry = FakeMcpRegistry(declarations=[fake_decl_1, fake_decl_2])
    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=None, mcp_registry=registry)
    declarations = agent._declarations()
    assert len(declarations) == 10  # 8 yerleşik + 2 sahte MCP
    assert fake_decl_1 in declarations
    assert fake_decl_2 in declarations


async def test_declarations_without_mcp_registry_only_builtins(tmp_path):
    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=None, mcp_registry=None)
    declarations = agent._declarations()
    assert len(declarations) == 8
