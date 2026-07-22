import pytest
from backend.skills.executor import SkillExecutor

pytestmark = pytest.mark.asyncio


class FakeTM:
    def start(self, description, runner):
        self.last = description
        return "Başlıyorum efendim."

    def status_text(self):
        return "Şu an üzerimde görev yok."


async def test_start_task_delegates():
    ex = SkillExecutor()
    ex.task_manager = FakeTM()
    reply = await ex.execute("start_task", {"description": "raporu yaz"})
    assert reply == "Başlıyorum efendim."
    assert ex.task_manager.last == "raporu yaz"


async def test_task_status_delegates():
    ex = SkillExecutor()
    ex.task_manager = FakeTM()
    assert "görev yok" in await ex.execute("task_status", {})


async def test_without_manager_graceful():
    ex = SkillExecutor()
    assert "hazır değil" in await ex.execute("start_task", {"description": "x"})
