import backend.config as config_module
from backend.core.long_term_memory import MemoryStore


def test_brain_loads_core_memory_into_system_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "MEMORY_DIR", tmp_path)
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Egemen İstanbul'a taşındı")

    from backend.core.brain import JarvisBrain
    brain = JarvisBrain()
    assert "Egemen İstanbul'a taşındı" in brain.system_prompt


def test_brain_without_memory_files_still_has_base_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "MEMORY_DIR", tmp_path)
    from backend.core.brain import JarvisBrain
    brain = JarvisBrain()
    assert "Jarvis" in brain.system_prompt


def test_brain_ignores_non_core_category(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "MEMORY_DIR", tmp_path)
    store = MemoryStore(tmp_path)
    store.save_fact("cok-ozel-bir-konu", "Bu çekirdek değil")

    from backend.core.brain import JarvisBrain
    brain = JarvisBrain()
    assert "Bu çekirdek değil" not in brain.system_prompt
