import pytest
from backend.skills.executor import SkillExecutor

pytestmark = pytest.mark.asyncio


class FakeStore:
    def __init__(self):
        self.saved = []
        self.todos_added = []

    def save_fact(self, category, text):
        self.saved.append((category, text))
        return f"Kaydedildi ({category}): {text}"

    def add_todo(self, item):
        self.todos_added.append(item)
        return f"Yapılacaklara eklendi: {item}"

    def complete_todo(self, item):
        return f"Tamamlandı: {item}"

    def read_todos(self):
        return "- [ ] örnek"

    def search_digests(self, query):
        return f"'{query}' için sonuç"


async def test_remember_delegates_with_default_category():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    reply = await ex.execute("remember", {"fact": "Bir şey"})
    assert "Kaydedildi" in reply
    assert ex.memory_store.saved == [("hakkimda", "Bir şey")]


async def test_remember_delegates_with_explicit_category():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    await ex.execute("remember", {"fact": "Kahve sevmiyor", "category": "ilgi-alanlarim"})
    assert ex.memory_store.saved == [("ilgi-alanlarim", "Kahve sevmiyor")]


async def test_add_todo_delegates():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    reply = await ex.execute("add_todo", {"item": "Rapor yaz"})
    assert "eklendi" in reply
    assert ex.memory_store.todos_added == ["Rapor yaz"]


async def test_complete_todo_delegates():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    reply = await ex.execute("complete_todo", {"item": "Rapor yaz"})
    assert "Tamamlandı" in reply


async def test_list_todos_delegates():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    reply = await ex.execute("list_todos", {})
    assert "örnek" in reply


async def test_recall_delegates():
    ex = SkillExecutor()
    ex.memory_store = FakeStore()
    reply = await ex.execute("recall", {"query": "geçen hafta"})
    assert "geçen hafta" in reply


async def test_all_five_graceful_without_store():
    ex = SkillExecutor()
    calls = [
        ("remember", {"fact": "x"}), ("add_todo", {"item": "x"}),
        ("complete_todo", {"item": "x"}), ("list_todos", {}), ("recall", {"query": "x"}),
    ]
    for tool, args in calls:
        reply = await ex.execute(tool, args)
        assert "hazır değil" in reply
