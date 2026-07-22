import asyncio
import pytest
from backend.core.task_manager import TaskManager, TaskState

pytestmark = pytest.mark.asyncio


def make_tm(events, timeout=0.2):
    async def event_cb(etype, msg):
        events.append((etype, msg))
    return TaskManager(event_cb=event_cb, approval_timeout=timeout)


async def test_single_task_lifecycle():
    events = []
    tm = make_tm(events)

    async def runner(tm_):
        return "iş bitti özeti"

    reply = tm.start("küçük iş", runner)
    assert "başl" in reply.lower()
    await asyncio.sleep(0.05)
    assert tm.state == TaskState.DONE
    assert ("started", "küçük iş") == events[0]
    assert events[-1][0] == "done" and "iş bitti özeti" in events[-1][1]


async def test_second_task_rejected_while_running():
    events = []
    tm = make_tm(events)
    gate = asyncio.Event()

    async def runner(tm_):
        await gate.wait()
        return "ok"

    tm.start("uzun iş", runner)
    reply2 = tm.start("ikinci iş", runner)
    assert "zaten" in reply2.lower()
    gate.set()
    await asyncio.sleep(0.05)


async def test_approval_approved_flow():
    events = []
    tm = make_tm(events)
    result = {}

    async def runner(tm_):
        result["approved"] = await tm_.request_approval("x dosyasını sileceğim")
        return "bitti"

    tm.start("silme işi", runner)
    await asyncio.sleep(0.05)
    assert tm.waiting_approval
    assert tm.state == TaskState.WAITING_APPROVAL
    reply = await tm.handle_utterance("evet onaylıyorum")
    assert reply is not None
    await asyncio.sleep(0.05)
    assert result["approved"] is True
    assert tm.state == TaskState.DONE


async def test_approval_timeout_is_rejection():
    events = []
    tm = make_tm(events, timeout=0.1)
    result = {}

    async def runner(tm_):
        result["approved"] = await tm_.request_approval("riskli iş")
        return "bitti"

    tm.start("işX", runner)
    await asyncio.sleep(0.3)
    assert result["approved"] is False   # sessizlik = RED
    assert tm.state == TaskState.DONE


async def test_unrelated_utterance_keeps_waiting():
    events = []
    tm = make_tm(events, timeout=5)

    async def runner(tm_):
        await tm_.request_approval("riskli iş")
        return "bitti"

    tm.start("işY", runner)
    await asyncio.sleep(0.05)
    assert await tm.handle_utterance("bu arada hava nasıl") is None
    assert tm.waiting_approval  # soru beklemede kalır
    await tm.handle_utterance("iptal")  # temizlik


async def test_runner_exception_fails_task():
    events = []
    tm = make_tm(events)

    async def runner(tm_):
        raise RuntimeError("patladı")

    tm.start("hatalı iş", runner)
    await asyncio.sleep(0.05)
    assert tm.state == TaskState.FAILED
    assert events[-1][0] == "failed"
