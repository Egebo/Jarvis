import asyncio
import types as pytypes
import pytest
from backend.core.agent import TaskAgent
from backend.skills.file_tools import FileTools

pytestmark = pytest.mark.asyncio


class FakePart:
    def __init__(self, text=None, function_call=None):
        self.text = text
        self.function_call = function_call


class FakeFC:
    def __init__(self, name, args):
        self.name = name
        self.args = args


def fake_response(parts):
    r = pytypes.SimpleNamespace()
    content = pytypes.SimpleNamespace(parts=parts, role="model")
    r.candidates = [pytypes.SimpleNamespace(content=content)]
    r.text = "".join(p.text or "" for p in parts)
    return r


def scripted_generate(script):
    """Her çağrıda script'ten sıradaki yanıtı döndüren async generate_fn."""
    it = iter(script)

    async def gen(contents):
        return next(it)
    return gen


async def approve_all(desc):
    return True


async def test_agent_executes_tool_then_finishes(tmp_path):
    script = [
        fake_response([FakePart(function_call=FakeFC("write_file",
                       {"path": "rapor.md", "content": "# Rapor"}))]),
        fake_response([FakePart(text="Rapor hazır efendim.")]),
    ]
    agent = TaskAgent("rapor yaz", FileTools(tmp_path), executor=None,
                      approval_cb=approve_all, generate_fn=scripted_generate(script))
    summary = await agent.run()
    assert summary == "Rapor hazır efendim."
    assert (tmp_path / "rapor.md").read_text(encoding="utf-8") == "# Rapor"


async def test_risky_tool_asks_approval_and_rejection_skips(tmp_path):
    ft = FileTools(tmp_path)
    ft.write_file("silinecek.txt", "x")
    script = [
        fake_response([FakePart(function_call=FakeFC("delete_path", {"path": "silinecek.txt"}))]),
        fake_response([FakePart(text="Silme reddedildi, işi bitirdim.")]),
    ]
    asked = []

    async def approval_cb(desc):
        asked.append(desc)
        return False

    agent = TaskAgent("temizlik", ft, executor=None,
                      approval_cb=approval_cb, generate_fn=scripted_generate(script))
    await agent.run()
    assert len(asked) == 1 and "sileceğim" in asked[0]
    assert (tmp_path / "silinecek.txt").exists()  # RED edildi, dosya duruyor


async def test_step_limit_forces_summary(tmp_path):
    loop_resp = fake_response([FakePart(function_call=FakeFC("list_dir", {"path": ""}))])
    final = fake_response([FakePart(text="Limit doldu, özet.")])
    script = [loop_resp] * 25 + [final]
    agent = TaskAgent("sonsuz iş", FileTools(tmp_path), executor=None,
                      approval_cb=approve_all, generate_fn=scripted_generate(script),
                      max_steps=25)
    summary = await agent.run()
    assert summary == "Limit doldu, özet."


async def test_retry_on_transient_error(tmp_path, monkeypatch):
    calls = {"n": 0}
    final = fake_response([FakePart(text="tamam")])

    async def flaky(contents):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503 UNAVAILABLE")
        return final

    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    agent = TaskAgent("iş", FileTools(tmp_path), executor=None,
                      approval_cb=approve_all, generate_fn=flaky)
    assert await agent.run() == "tamam"
    assert calls["n"] == 3


async def test_failure_saves_partial_result(tmp_path):
    calls = {"n": 0}

    async def script(contents):
        calls["n"] += 1
        if calls["n"] == 1:
            return fake_response([FakePart(function_call=FakeFC("write_file",
                                  {"path": "notlar.md", "content": "ilerleme var"}))])
        raise ValueError("model çöktü")

    agent = TaskAgent("uzun görev", FileTools(tmp_path), executor=None,
                      approval_cb=approve_all, generate_fn=script)
    with pytest.raises(RuntimeError) as excinfo:
        await agent.run()
    assert "Kısmî sonucu" in str(excinfo.value)
    kismi_dosyalar = list(tmp_path.glob("kismi-sonuc-*.md"))
    assert len(kismi_dosyalar) == 1
    icerik = kismi_dosyalar[0].read_text(encoding="utf-8")
    assert "uzun görev" in icerik
