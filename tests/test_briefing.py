import types as pytypes
import pytest
from backend.core.briefing import generate_briefing_text

pytestmark = pytest.mark.asyncio


def fake_response(text):
    return pytypes.SimpleNamespace(text=text)


async def test_returns_text_as_is_and_prompt_contains_inputs():
    captured = {}

    async def gen(prompt):
        captured["prompt"] = prompt
        return fake_response("Günaydın Egemen, bugün hava güzel.")

    text = await generate_briefing_text(
        weather="Bugün açık, 24 derece",
        todos="Rapor teslimi",
        digests="Dün yeni işe başladığından bahsetti",
        generate_fn=gen,
    )
    assert text == "Günaydın Egemen, bugün hava güzel."
    assert "Bugün açık, 24 derece" in captured["prompt"]
    assert "Rapor teslimi" in captured["prompt"]
    assert "Dün yeni işe başladığından bahsetti" in captured["prompt"]


async def test_generate_fn_exception_returns_none_without_raising():
    async def gen(prompt):
        raise RuntimeError("503 UNAVAILABLE")

    text = await generate_briefing_text("açık", "yok", "yok", generate_fn=gen)
    assert text is None


async def test_empty_string_response_returns_none():
    async def gen(prompt):
        return fake_response("")

    text = await generate_briefing_text("açık", "yok", "yok", generate_fn=gen)
    assert text is None


async def test_all_empty_inputs_dont_crash_and_use_placeholder():
    captured = {}

    async def gen(prompt):
        captured["prompt"] = prompt
        return fake_response("Günaydın efendim!")

    text = await generate_briefing_text("", "", "", generate_fn=gen)
    assert text == "Günaydın efendim!"
    assert captured["prompt"].count("(yok)") == 3
