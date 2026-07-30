from google.genai import types

import backend.config as config_module


class FakeMcpRegistry:
    def read_only_declarations(self):
        return [
            types.FunctionDeclaration(
                name="github__list_commits",
                description="Sahte MCP aracı 1",
                parameters_json_schema={"type": "object", "properties": {}, "required": []},
            ),
            types.FunctionDeclaration(
                name="calendar__list_events",
                description="Sahte MCP aracı 2",
                parameters_json_schema={"type": "object", "properties": {}, "required": []},
            ),
        ]


def test_brain_with_mcp_registry_adds_read_only_declarations(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "MEMORY_DIR", tmp_path)
    from backend.core.brain import JarvisBrain

    fake = FakeMcpRegistry()
    brain = JarvisBrain(mcp_registry=fake)

    names = [d.name for d in brain.tools[0].function_declarations]
    assert "github__list_commits" in names
    assert "calendar__list_events" in names
    # Mevcut sabit araçlardan biri de hâlâ orada olmalı
    assert "web_search" in names


def test_brain_without_mcp_registry_tool_count_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "MEMORY_DIR", tmp_path)
    from backend.core.brain import JarvisBrain

    brain_default = JarvisBrain()
    brain_none = JarvisBrain(mcp_registry=None)

    default_count = len(brain_default.tools[0].function_declarations)
    none_count = len(brain_none.tools[0].function_declarations)

    assert default_count == none_count

    names = [d.name for d in brain_default.tools[0].function_declarations]
    assert "github__list_commits" not in names
    assert "calendar__list_events" not in names
