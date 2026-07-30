import pytest
from backend.skills.executor import SkillExecutor

pytestmark = pytest.mark.asyncio


class FakeMcpRegistry:
    def __init__(self, has_result=True, read_only=True):
        self._has_result = has_result
        self._read_only = read_only
        self.has_calls = []
        self.call_calls = []
        self.raise_on_call = False

    def has(self, name):
        self.has_calls.append(name)
        return self._has_result

    def is_read_only(self, name):
        return self._read_only

    async def call(self, name, args):
        self.call_calls.append((name, args))
        if self.raise_on_call:
            raise RuntimeError("mcp patladı")
        return f"MCP sonucu ({name}): {args}"


async def test_unknown_tool_delegates_to_mcp_when_has_true():
    ex = SkillExecutor()
    ex.mcp_registry = FakeMcpRegistry(has_result=True)
    reply = await ex.execute("github__list_repos", {"owner": "egebo"})
    assert "MCP sonucu" in reply
    assert ex.mcp_registry.call_calls == [("github__list_repos", {"owner": "egebo"})]


async def test_unknown_tool_still_unknown_when_has_false():
    ex = SkillExecutor()
    ex.mcp_registry = FakeMcpRegistry(has_result=False)
    reply = await ex.execute("github__list_repos", {})
    assert "Bilinmeyen araç" in reply
    assert ex.mcp_registry.call_calls == []


async def test_unknown_tool_still_unknown_when_registry_none():
    ex = SkillExecutor()
    reply = await ex.execute("github__list_repos", {})
    assert "Bilinmeyen araç" in reply


async def test_static_handler_takes_priority_over_mcp():
    # get_weather is a real static handler (it hits the network); to keep this
    # test fast/deterministic/offline-safe we use task_status instead, which
    # is also a static handler and gracefully no-ops without a task_manager -
    # what matters is that it's a name present in the static `handlers` dict.
    ex = SkillExecutor()
    fake_registry = FakeMcpRegistry(has_result=True)
    ex.mcp_registry = fake_registry
    reply = await ex.execute("task_status", {})
    assert "hazır değil" in reply
    assert "MCP sonucu" not in reply
    assert fake_registry.has_calls == []
    assert fake_registry.call_calls == []


async def test_mcp_call_exception_wrapped_as_arac_hatasi():
    ex = SkillExecutor()
    fake_registry = FakeMcpRegistry(has_result=True)
    fake_registry.raise_on_call = True
    ex.mcp_registry = fake_registry
    reply = await ex.execute("github__list_repos", {})
    assert "Araç hatası" in reply
    assert "mcp patladı" in reply


async def test_non_read_only_mcp_tool_refused_without_calling():
    # Savunma katmanı: canlı sohbetin tool listesi normalde sadece salt-okunur
    # MCP araçları içerir (brain.py), ama execute() bunu kendi başına da
    # doğrular - is_read_only()=False ise call() HİÇ tetiklenmemeli.
    ex = SkillExecutor()
    fake_registry = FakeMcpRegistry(has_result=True, read_only=False)
    ex.mcp_registry = fake_registry
    reply = await ex.execute("github__delete_repo", {})
    assert "start_task" in reply
    assert fake_registry.call_calls == []
