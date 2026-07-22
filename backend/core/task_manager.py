"""
TaskManager: görev yaşam döngüsü + sesli onay akışı.
Spec: docs/superpowers/specs/2026-07-22-gorev-ajani-design.md
"""
import asyncio
import re
from enum import Enum
from typing import Awaitable, Callable

from backend.config import APPROVAL_TIMEOUT

APPROVE_WORDS = {"evet", "onayla", "onaylıyorum", "yap", "tamam"}
REJECT_WORDS = {"hayır", "hayir", "iptal", "yapma", "dur"}


def parse_approval(text: str) -> bool | None:
    """Kelime bazlı onay/red algılama. Red kelimesi varsa RED kazanır."""
    words = set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))
    if words & REJECT_WORDS:
        return False
    if words & APPROVE_WORDS:
        return True
    return None


class TaskState(str, Enum):
    """Görev durum makinesi."""
    IDLE = "idle"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    FAILED = "failed"


class TaskManager:
    """Tek görev (MVP). Görevi arka planda çalıştırır, onay akışını yönetir."""

    def __init__(self, event_cb: Callable[[str, str], Awaitable[None]],
                 approval_timeout: float = APPROVAL_TIMEOUT):
        self._event_cb = event_cb
        self._timeout = approval_timeout
        self.state = TaskState.IDLE
        self.description = ""
        self._task: asyncio.Task | None = None
        self._approval_future: asyncio.Future | None = None
        self.pending_action = ""

    # -- yaşam döngüsü --
    def start(self, description: str,
              runner: Callable[["TaskManager"], Awaitable[str]]) -> str:
        if self.state in (TaskState.RUNNING, TaskState.WAITING_APPROVAL):
            return f"Şu an zaten bir görev üzerindeyim: {self.description}. Bitince yenisini alabilirim."
        self.state = TaskState.RUNNING
        self.description = description
        self._task = asyncio.get_event_loop().create_task(self._run(runner))
        return "Başlıyorum efendim, bitince haber veririm."

    async def _run(self, runner):
        await self._event_cb("started", self.description)
        try:
            summary = await runner(self)
            self.state = TaskState.DONE
            await self._event_cb("done", summary)
        except Exception as e:
            self.state = TaskState.FAILED
            await self._event_cb("failed", f"Görev başarısız oldu: {e}")

    def status_text(self) -> str:
        return {
            TaskState.IDLE: "Şu an üzerimde görev yok.",
            TaskState.RUNNING: f"Görev sürüyor: {self.description}",
            TaskState.WAITING_APPROVAL: f"Onayını bekliyorum: {self.pending_action}",
            TaskState.DONE: f"Son görev tamamlandı: {self.description}",
            TaskState.FAILED: f"Son görev başarısız oldu: {self.description}",
        }[self.state]

    # -- onay akışı --
    @property
    def waiting_approval(self) -> bool:
        return self.state == TaskState.WAITING_APPROVAL

    async def request_approval(self, action_desc: str) -> bool:
        """Ajan riskli adımda çağırır. Zaman aşımı = RED (sessizlik onay değildir)."""
        self.state = TaskState.WAITING_APPROVAL
        self.pending_action = action_desc
        self._approval_future = asyncio.get_event_loop().create_future()
        await self._event_cb("approval_request", action_desc)
        try:
            approved = await asyncio.wait_for(self._approval_future, timeout=self._timeout)
        except asyncio.TimeoutError:
            approved = False
        finally:
            self._approval_future = None
            self.pending_action = ""
            self.state = TaskState.RUNNING
        return approved

    async def handle_utterance(self, text: str) -> str | None:
        """Onay beklenirken gelen konuşma. Onay/red yakalarsa kısa yanıt döner."""
        if not self.waiting_approval or self._approval_future is None:
            return None
        verdict = parse_approval(text)
        if verdict is None:
            return None
        if self._approval_future.done():
            return None
        self._approval_future.set_result(verdict)
        return "Anlaşıldı, devam ediyorum." if verdict else "Anlaşıldı, o adımı iptal ediyorum."
