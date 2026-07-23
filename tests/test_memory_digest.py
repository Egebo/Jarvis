import types as pytypes
import asyncio
import pytest
from backend.core.long_term_memory import MemoryStore
from backend.core.memory_digest import summarize_and_save

pytestmark = pytest.mark.asyncio


def fake_response_with_call(name, args):
    fc = pytypes.SimpleNamespace(name=name, args=args)
    part = pytypes.SimpleNamespace(function_call=fc, text=None)
    content = pytypes.SimpleNamespace(parts=[part])
    return pytypes.SimpleNamespace(candidates=[pytypes.SimpleNamespace(content=content)], text="")


def fake_response_no_call(text="Önemli bir şey yok."):
    part = pytypes.SimpleNamespace(function_call=None, text=text)
    content = pytypes.SimpleNamespace(parts=[part])
    return pytypes.SimpleNamespace(candidates=[pytypes.SimpleNamespace(content=content)], text=text)


async def test_empty_messages_saves_nothing_and_never_calls_generate(tmp_path):
    store = MemoryStore(tmp_path)

    async def gen(transcript):
        raise AssertionError("generate_fn çağrılmamalıydı")

    saved = await summarize_and_save([], store, generate_fn=gen)
    assert saved is False
    assert list((tmp_path / "digests").glob("*.md")) == []


async def test_model_declines_saves_nothing(tmp_path):
    store = MemoryStore(tmp_path)
    messages = [{"role": "user", "content": "Merhaba"}, {"role": "model", "content": "Merhaba efendim"}]

    async def gen(transcript):
        return fake_response_no_call()

    saved = await summarize_and_save(messages, store, generate_fn=gen)
    assert saved is False
    assert list((tmp_path / "digests").glob("*.md")) == []


async def test_saves_digest_and_facts(tmp_path):
    store = MemoryStore(tmp_path)
    messages = [
        {"role": "user", "content": "Yeni bir işe başladım, artık İstanbul'dayım."},
        {"role": "model", "content": "Tebrikler efendim, hayırlı olsun!"},
    ]

    async def gen(transcript):
        assert "İstanbul" in transcript
        return fake_response_with_call("extract_memory", {
            "digest": "Egemen yeni işine başladığını ve İstanbul'a taşındığını söyledi.",
            "facts": [{"category": "hakkimda", "text": "İstanbul'da yaşıyor, yeni işe başladı"}],
        })

    saved = await summarize_and_save(messages, store, generate_fn=gen)
    assert saved is True
    digest_files = list((tmp_path / "digests").glob("*.md"))
    assert len(digest_files) == 1
    assert "İstanbul'a taşındığını" in digest_files[0].read_text(encoding="utf-8")
    hakkimda = (tmp_path / "hakkimda.md").read_text(encoding="utf-8")
    assert "İstanbul'da yaşıyor" in hakkimda


async def test_non_text_messages_are_skipped_in_transcript(tmp_path):
    store = MemoryStore(tmp_path)
    messages = [
        {"role": "user", "content": "Not al: kahve sevmem"},
        {"role": "model", "content": [object()]},  # araç çağrısı parçaları, düz metin değil
    ]

    async def gen(transcript):
        assert "kahve" in transcript
        assert transcript.count("\n") == 0  # sadece 1 metin satırı kaldı
        return fake_response_no_call()

    await summarize_and_save(messages, store, generate_fn=gen)


async def test_retries_once_on_error_then_succeeds(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    messages = [{"role": "user", "content": "Not al: kahve sevmem"}]
    calls = {"n": 0}

    async def gen(transcript):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 UNAVAILABLE")
        return fake_response_with_call("extract_memory", {
            "digest": None,
            "facts": [{"category": "ilgi-alanlarim", "text": "Kahve sevmiyor"}],
        })

    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    saved = await summarize_and_save(messages, store, generate_fn=gen)
    assert saved is True
    assert calls["n"] == 2
    assert list((tmp_path / "digests").glob("*.md")) == []
    assert "Kahve sevmiyor" in (tmp_path / "ilgi-alanlarim.md").read_text(encoding="utf-8")


async def test_gives_up_after_retry_fails(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    messages = [{"role": "user", "content": "Bir şeyler konuştuk"}]

    async def gen(transcript):
        raise RuntimeError("503 UNAVAILABLE")

    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    saved = await summarize_and_save(messages, store, generate_fn=gen)
    assert saved is False
