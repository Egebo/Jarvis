# Kalıcı Hafıza (Faz 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis'e oturumlar arası kalıcı hafıza kazandırmak: açık "not al" komutları, yapılacaklar listesi, ve konuşma sonunda arka planda otomatik öğrenme/özetleme.

**Architecture:** Dosya tabanlı depo (`MemoryStore`, kategorilere ayrılmış Markdown dosyaları, repo dışında) + arka plan LLM özetleyici (`summarize_and_save`, function-calling ile yapılandırılmış çıkarım) + sohbet beynine 5 yeni araç + oturum başı sistem promptuna otomatik enjeksiyon.

**Tech Stack:** Python 3.13, google-genai (mevcut), pytest/pytest-asyncio (Faz 1'den kurulu), Markdown dosya deposu (veritabanı yok).

## Global Constraints

- `MEMORY_DIR` varsayılanı repo DIŞINDA: `~/Desktop/Jarvis-Memory` (env: `JARVIS_MEMORY_DIR`) — `WORKSPACE_DIR` ile aynı desen; kişisel bilgi git'e karışmasın.
- Çekirdek kategoriler (her oturumda TAM içerikle yüklenir): `karakter-tercihler`, `hakkimda`, `ilgi-alanlarim`. Yeni kategori adları serbest; dosya adı `category.strip().lower().replace(" ", "-") + ".md"`.
- `digests/` ve `todos.md` her zaman yüklenmez; sadece `recall`/`list_todos` araçlarıyla okunur.
- Otomatik özetleme tetikleyicileri: SADECE mevcut `WebSocketDisconnect` ve `reset` olayları (yeni zamanlayıcı YOK).
- Arka plan özetleme hatası: 1 kez tekrar dene (`RETRY_DELAY = 5` sn), yine olmazsa sessizce vazgeç (loglayıp `False` dön) — sohbeti asla etkilemez.
- `search_digests`/`recall`: basit case-insensitive alt-dize araması (embedding/vektör YOK), en fazla son 5 eşleşen gün.
- Çıkarım prompt'u cömert olmalı: şüpheli durumda kaydetme tarafına eğilsin; önemsiz sohbette (`extract_memory` hiç çağrılmazsa) hiçbir dosya yazılmaz.
- Türkçe kullanıcı/dosya metinleri; uzun tire (—) kullanma. Komutlar `./venv/Scripts/python.exe` ile repo kökünden. Branch: `kalici-hafiza` (yeni, `main`'den).
- Commit mesajlarının sonuna `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` eklenir.

---

### Task 1: MemoryStore (config + depolama katmanı)

**Files:**
- Modify: `backend/config.py:82-89` (mevcut "Görev Ajanı" bloğunun hemen altına yeni blok eklenir)
- Create: `backend/core/long_term_memory.py`
- Test: `tests/test_long_term_memory.py`

**Interfaces:**
- Consumes: `backend.config.MEMORY_DIR`
- Produces: `MemoryStore(base_dir: Path)` sınıfı — metodlar: `save_fact(category: str, text: str) -> str`, `append_digest(text: str, when: datetime | None = None) -> str`, `read_core_files() -> str`, `add_todo(item: str) -> str`, `complete_todo(item: str) -> str`, `read_todos() -> str`, `search_digests(query: str) -> str`. Ayrıca modül sabiti `CORE_CATEGORIES = ("karakter-tercihler", "hakkimda", "ilgi-alanlarim")`.

- [ ] **Step 1: config.py'ye MEMORY_DIR ekle**

`backend/config.py` dosyasının sonuna (mevcut `AGENT_MAX_STEPS` satırından sonra) ekle:

```python

# ─── Kalıcı Hafıza ──────────────────────────────────────────────────────────
# WORKSPACE_DIR gibi repo DIŞINDA tutulur — kişisel bilgi git'e karışmasın.
MEMORY_DIR = Path(os.getenv("JARVIS_MEMORY_DIR",
                            str(Path.home() / "Desktop" / "Jarvis-Memory")))
```

(`Path` zaten dosyanın üst kısmında "Görev Ajanı" bloğunda import edilmiş durumda, tekrar import etmeye gerek yok.)

- [ ] **Step 2: Import doğrula**

Run: `./venv/Scripts/python.exe -c "from backend.config import MEMORY_DIR; print(MEMORY_DIR)"`
Expected: `C:\Users\bozca\Desktop\Jarvis-Memory` (veya eşdeğeri)

- [ ] **Step 3: Failing testleri yaz** (`tests/test_long_term_memory.py`)

```python
from datetime import datetime
from backend.core.long_term_memory import MemoryStore


def test_save_fact_creates_file_with_header_and_entry(tmp_path):
    store = MemoryStore(tmp_path)
    msg = store.save_fact("hakkimda", "Egemen Sakarya Üniversitesi mezunu")
    assert "hakkimda" in msg
    content = (tmp_path / "hakkimda.md").read_text(encoding="utf-8")
    assert "Egemen Sakarya Üniversitesi mezunu" in content


def test_save_fact_appends_without_duplicate_header(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Birinci gerçek")
    store.save_fact("hakkimda", "İkinci gerçek")
    content = (tmp_path / "hakkimda.md").read_text(encoding="utf-8")
    assert content.count("# hakkimda") == 1
    assert "Birinci gerçek" in content and "İkinci gerçek" in content


def test_save_fact_new_category_adds_to_index(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("is-hayati", "Yeni bir işe başladı")
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "is-hayati" in index


def test_save_fact_existing_category_does_not_duplicate_index(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Bir")
    store.save_fact("hakkimda", "İki")
    index = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert index.count("hakkimda") == 1


def test_append_digest_creates_dated_file(tmp_path):
    store = MemoryStore(tmp_path)
    when = datetime(2026, 7, 22, 14, 30)
    store.append_digest("Bugün Faz 2 konuşuldu.", when=when)
    content = (tmp_path / "digests" / "2026-07-22.md").read_text(encoding="utf-8")
    assert "14:30" in content
    assert "Bugün Faz 2 konuşuldu." in content


def test_append_digest_same_day_appends_new_section(tmp_path):
    store = MemoryStore(tmp_path)
    store.append_digest("Sabah konuşması.", when=datetime(2026, 7, 22, 9, 0))
    store.append_digest("Akşam konuşması.", when=datetime(2026, 7, 22, 20, 0))
    content = (tmp_path / "digests" / "2026-07-22.md").read_text(encoding="utf-8")
    assert "Sabah konuşması." in content
    assert "Akşam konuşması." in content
    assert content.count("2026-07-22") == 1  # tek başlık, iki alt bölüm


def test_read_core_files_includes_only_core_categories(tmp_path):
    store = MemoryStore(tmp_path)
    store.save_fact("hakkimda", "Çekirdek bilgi")
    store.save_fact("cok-ozel-bir-konu", "Çekirdek dışı bilgi")
    core_text = store.read_core_files()
    assert "Çekirdek bilgi" in core_text
    assert "Çekirdek dışı bilgi" not in core_text


def test_read_core_files_empty_store_returns_empty_string(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.read_core_files().strip() == ""


def test_add_and_read_todos(tmp_path):
    store = MemoryStore(tmp_path)
    store.add_todo("Sunucuyu yeniden başlat")
    todos = store.read_todos()
    assert "- [ ] Sunucuyu yeniden başlat" in todos


def test_complete_todo_marks_checkbox(tmp_path):
    store = MemoryStore(tmp_path)
    store.add_todo("Rapor yaz")
    msg = store.complete_todo("Rapor yaz")
    assert "Tamamlandı" in msg
    todos = store.read_todos()
    assert "- [x] Rapor yaz" in todos
    assert "- [ ] Rapor yaz" not in todos


def test_complete_todo_not_found(tmp_path):
    store = MemoryStore(tmp_path)
    msg = store.complete_todo("Olmayan madde")
    assert "bulunamadı" in msg


def test_read_todos_empty(tmp_path):
    store = MemoryStore(tmp_path)
    assert "boş" in store.read_todos()


def test_search_digests_finds_match(tmp_path):
    store = MemoryStore(tmp_path)
    store.append_digest("Görev ajanı hakkında konuşuldu.", when=datetime(2026, 7, 20, 10, 0))
    result = store.search_digests("görev ajanı")
    assert "Görev ajanı hakkında konuşuldu." in result


def test_search_digests_no_match(tmp_path):
    store = MemoryStore(tmp_path)
    result = store.search_digests("alakasız bir konu")
    assert "bulunamadı" in result
```

- [ ] **Step 4: Testlerin FAIL ettiğini doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_long_term_memory.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.core.long_term_memory'`

- [ ] **Step 5: Implementasyon** (`backend/core/long_term_memory.py`)

```python
"""
Kalıcı hafıza deposu — Egemen'le ilgili bilgiyi kategorilere ayrılmış
Markdown dosyalarında tutar. Repo dışında (backend.config.MEMORY_DIR).
Spec: docs/superpowers/specs/2026-07-22-kalici-hafiza-design.md
"""
from datetime import datetime
from pathlib import Path

# Her oturum başında TAM içeriğiyle sistem promptuna yüklenen kategoriler.
# Diğer kategoriler (ör. sonradan açılan konu dosyaları) sadece recall() ile aranır.
CORE_CATEGORIES = ("karakter-tercihler", "hakkimda", "ilgi-alanlarim")


class MemoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "digests").mkdir(exist_ok=True)
        self._index_path = self.base_dir / "MEMORY.md"

    def _category_path(self, category: str) -> Path:
        safe = category.strip().lower().replace(" ", "-")
        return self.base_dir / f"{safe}.md"

    def save_fact(self, category: str, text: str) -> str:
        path = self._category_path(category)
        is_new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {category}\n\n")
            f.write(f"- {text}\n")
        if is_new:
            self._add_to_index(category, path.name)
        return f"Kaydedildi ({category}): {text}"

    def _add_to_index(self, category: str, filename: str):
        with self._index_path.open("a", encoding="utf-8") as f:
            f.write(f"- [{category}]({filename})\n")

    def append_digest(self, text: str, when: datetime | None = None) -> str:
        when = when or datetime.now()
        path = self.base_dir / "digests" / f"{when.strftime('%Y-%m-%d')}.md"
        is_new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {when.strftime('%Y-%m-%d')}\n\n")
            f.write(f"## {when.strftime('%H:%M')}\n\n{text}\n\n")
        return f"Özet kaydedildi: {path.name}"

    def read_core_files(self) -> str:
        parts = []
        if self._index_path.exists():
            parts.append(self._index_path.read_text(encoding="utf-8"))
        for category in CORE_CATEGORIES:
            path = self._category_path(category)
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def add_todo(self, item: str) -> str:
        path = self.base_dir / "todos.md"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- [ ] {item}\n")
        return f"Yapılacaklara eklendi: {item}"

    def complete_todo(self, item: str) -> str:
        path = self.base_dir / "todos.md"
        if not path.exists():
            return "Yapılacaklar listesi boş."
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("- [ ]") and item.lower() in line.lower():
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return f"Tamamlandı: {item}"
        return f"'{item}' listede bulunamadı."

    def read_todos(self) -> str:
        path = self.base_dir / "todos.md"
        if not path.exists():
            return "Yapılacaklar listesi boş."
        return path.read_text(encoding="utf-8")

    def search_digests(self, query: str) -> str:
        digests_dir = self.base_dir / "digests"
        query_lower = query.lower()
        matches = []
        for path in sorted(digests_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if query_lower in text.lower():
                matches.append(f"### {path.stem}\n{text}")
        if not matches:
            return f"'{query}' ile ilgili geçmiş kayıt bulunamadı."
        return "\n\n".join(matches[-5:])
```

- [ ] **Step 6: Testlerin PASS ettiğini doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_long_term_memory.py -v`
Expected: 14 passed

- [ ] **Step 7: Commit**

```bash
git checkout -b kalici-hafiza
git add backend/config.py backend/core/long_term_memory.py tests/test_long_term_memory.py
git commit -m "feat: MemoryStore ve MEMORY_DIR yapılandırması

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Arka plan özetleme (`summarize_and_save`)

**Files:**
- Create: `backend/core/memory_digest.py`
- Test: `tests/test_memory_digest.py`

**Interfaces:**
- Consumes: `backend.core.long_term_memory.MemoryStore` (Task 1), `backend.config.GEMINI_API_KEY`, `backend.config.GEMINI_MODEL`
- Produces: `async def summarize_and_save(messages: list, store: MemoryStore, generate_fn=None) -> bool`. `messages` formatı: `ConversationMemory.get_messages()` ile aynı — `[{"role": "user"|"model", "content": str | Part-listesi}]`. `generate_fn(transcript: str) -> response` (async; `response.candidates[0].content.parts` üzerinde `function_call.name`/`function_call.args` bekler — TaskAgent'ın test deseniyle aynı).

- [ ] **Step 1: Failing testleri yaz** (`tests/test_memory_digest.py`)

```python
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
        {"role": "model", "content": [object()]},  # araç çağrısı parçaları — düz metin değil
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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_memory_digest.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.core.memory_digest'`

- [ ] **Step 3: Implementasyon** (`backend/core/memory_digest.py`)

```python
"""
Oturum bitince (bağlantı kopması veya sıfırlama) konuşmadan kalıcı bilgi +
günlük özet çıkarır. Arka planda çalışır, sohbet gecikmesine hiç dokunmaz.
Spec: docs/superpowers/specs/2026-07-22-kalici-hafiza-design.md
"""
import asyncio

from backend.config import GEMINI_API_KEY, GEMINI_MODEL
from backend.core.long_term_memory import MemoryStore

EXTRACTION_PROMPT = """Aşağıda Jarvis (kişisel yapay zeka asistanı) ile Egemen
arasında geçen bir konuşma var.

Bu konuşmadan:
1. Kısa bir günlük özet çıkar (digest): 2-4 cümle, neler konuşuldu/kararlaştırıldı.
2. Gelecekte hatırlanmaya değer KALICI bilgi varsa (Egemen'in bir tercihi, bir
   gerçek, bir ilgi alanı, önemli bir karar) bunları facts listesine ekle.
   Şüpheliysen bile kaydetme tarafını tercih et; az bilgi kaydetmemek, fazla
   bilgi kaydetmekten daha kötü bir sonuçtur.

Sadece gündelik/önemsiz bir sohbetse (selamlaşma, tek soru-cevap, konu yok)
extract_memory'yi HİÇ ÇAĞIRMA.

---KONUŞMA---
"""

RETRY_DELAY = 5  # sn; tek tekrar denemesi


def _transcript_from_messages(messages: list) -> str:
    lines = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = "Egemen" if msg.get("role") == "user" else "Jarvis"
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_declaration():
    from google.genai import types
    return types.FunctionDeclaration(
        name="extract_memory",
        description=(
            "Konuşmadan çıkarılan kalıcı bilgiyi kaydeder. Sadece gerçekten "
            "hatırlanmaya değer bir şey varsa çağır."
        ),
        parameters_json_schema={
            "type": "object",
            "properties": {
                "digest": {"type": "string", "description": "Konuşmanın 2-4 cümlelik Türkçe özeti"},
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string",
                                        "description": "karakter-tercihler, hakkimda, ilgi-alanlarim veya yeni bir konu adı"},
                            "text": {"type": "string",
                                    "description": "Kalıcı olarak hatırlanacak tek bir gerçek/tercih, kısa cümle"}
                        },
                        "required": ["category", "text"]
                    }
                }
            },
            "required": []
        }
    )


async def _real_generate(transcript: str):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[_extract_declaration()])],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    return await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=EXTRACTION_PROMPT + transcript,
        config=config,
    )


def _parse_extraction(response) -> dict:
    parts = response.candidates[0].content.parts or []
    for p in parts:
        fc = getattr(p, "function_call", None)
        if fc and fc.name == "extract_memory":
            return dict(fc.args) if fc.args else {}
    return {}


async def summarize_and_save(messages: list, store: MemoryStore, generate_fn=None) -> bool:
    """
    Oturum bittiğinde çağrılır. Konuşmadan digest + kalıcı bilgi çıkarır,
    store'a yazar. Önemli bir şey yoksa hiçbir dosya yazmaz.
    Dönüş: bir şey kaydedildiyse True.
    """
    transcript = _transcript_from_messages(messages)
    if not transcript.strip():
        return False

    generate = generate_fn or _real_generate

    result = None
    for attempt in range(2):  # ilk deneme + 1 tekrar
        try:
            response = await generate(transcript)
            result = _parse_extraction(response)
            break
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(RETRY_DELAY)
                continue
            print(f"⚠️ Hafıza özetleme başarısız, atlanıyor: {e}")
            return False

    if result is None:
        return False

    saved = False
    if result.get("digest"):
        store.append_digest(result["digest"])
        saved = True
    for fact in result.get("facts") or []:
        store.save_fact(fact["category"], fact["text"])
        saved = True
    return saved
```

- [ ] **Step 4: PASS doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_memory_digest.py -v`
Expected: 6 passed

- [ ] **Step 5: Tüm testleri çalıştır ve commit**

Run: `./venv/Scripts/python.exe -m pytest -v`
Expected: hepsi passed (Task 1'in 14 testi dahil, toplam artıyor)

```bash
git add backend/core/memory_digest.py tests/test_memory_digest.py
git commit -m "feat: arka plan konuşma özetleme (summarize_and_save)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: SkillExecutor'a 5 hafıza aracı bağlama

**Files:**
- Modify: `backend/skills/executor.py:19-21` (`__init__`), `:24-39` (`handlers` dict)
- Test: `tests/test_executor_memory_tools.py`

**Interfaces:**
- Consumes: `MemoryStore` arayüzü (Task 1) — sahte (`FakeStore`) ile test edilir, gerçek bağlantı Task 5'te.
- Produces: `SkillExecutor.memory_store` attribute (varsayılan `None`, server.py lifespan'de set edilir); `remember(fact, category="hakkimda")`, `add_todo(item)`, `complete_todo(item)`, `list_todos()`, `recall(query)` metodları.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_executor_memory_tools.py`)

```python
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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_executor_memory_tools.py -v`
Expected: `Bilinmeyen araç: remember` içeren assert hatası (5 test)

- [ ] **Step 3: executor.py değişiklikleri**

`backend/skills/executor.py:19-21` (`__init__`) şu anki hali:

```python
    def __init__(self):
        self._search_client = None
        self.task_manager = None   # server.py lifespan'de set edilir
```

şuna değiştir:

```python
    def __init__(self):
        self._search_client = None
        self.task_manager = None   # server.py lifespan'de set edilir
        self.memory_store = None   # server.py lifespan'de set edilir
```

`backend/skills/executor.py:24-39` (`handlers` dict) şu anki hali:

```python
        handlers = {
            "web_search": self.web_search,
            "open_application": self.open_application,
            "open_url": self.open_url,
            # "run_command": self.run_command,  # BİLİNÇLİ KAPALI: STT yanlış
            # anlarsa tehlikeli komut çalıştırabilir. Açmadan önce sesli onay
            # mekanizması eklenmeli (Egemen'in isteği, 17 Tem 2026).
            "system_info": self.system_info,
            "set_reminder": self.set_reminder,
            "get_weather": self.get_weather,
            "control_media": self.control_media,
            "get_now_playing": self.get_now_playing,
            "take_screenshot": self.take_screenshot,
            "start_task": self.start_task,
            "task_status": self.task_status,
        }
```

şuna değiştir (son 5 satır eklendi):

```python
        handlers = {
            "web_search": self.web_search,
            "open_application": self.open_application,
            "open_url": self.open_url,
            # "run_command": self.run_command,  # BİLİNÇLİ KAPALI: STT yanlış
            # anlarsa tehlikeli komut çalıştırabilir. Açmadan önce sesli onay
            # mekanizması eklenmeli (Egemen'in isteği, 17 Tem 2026).
            "system_info": self.system_info,
            "set_reminder": self.set_reminder,
            "get_weather": self.get_weather,
            "control_media": self.control_media,
            "get_now_playing": self.get_now_playing,
            "take_screenshot": self.take_screenshot,
            "start_task": self.start_task,
            "task_status": self.task_status,
            "remember": self.remember,
            "add_todo": self.add_todo,
            "complete_todo": self.complete_todo,
            "list_todos": self.list_todos,
            "recall": self.recall,
        }
```

Yeni bir bölüm ekle — dosyanın `# ─── Görev Ajanı köprüsü` bölümünden hemen sonra (start_task/task_status metodlarının bittiği yerde, `# ─── Web Arama` bölümünden önce):

```python
    # ─── Kalıcı Hafıza köprüsü ─────────────────────────────────────────────────
    async def remember(self, fact: str, category: str = "hakkimda") -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.save_fact(category, fact)

    async def add_todo(self, item: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.add_todo(item)

    async def complete_todo(self, item: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.complete_todo(item)

    async def list_todos(self) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.read_todos()

    async def recall(self, query: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.search_digests(query)
```

- [ ] **Step 4: PASS doğrula + tüm testler**

Run: `./venv/Scripts/python.exe -m pytest -v`
Expected: hepsi passed

- [ ] **Step 5: Commit**

```bash
git add backend/skills/executor.py tests/test_executor_memory_tools.py
git commit -m "feat: sohbet beynine 5 hafıza aracı bağlama (remember/todo/recall)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: JarvisBrain'e hafıza enjeksiyonu + araç bildirimleri

**Files:**
- Modify: `backend/core/brain.py:13-17` (`__init__`), `:159` civarı (`declarations` listesinin sonu), `:182-189` (`think()` içindeki `system_instruction`)
- Test: `tests/test_brain_memory.py`

**Interfaces:**
- Consumes: `MemoryStore` (Task 1), `backend.config.MEMORY_DIR`
- Produces: `JarvisBrain.system_prompt: str` attribute (oturum başı bir kez hesaplanır, `think()` bunu kullanır)

- [ ] **Step 1: Failing testleri yaz** (`tests/test_brain_memory.py`)

```python
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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_brain_memory.py -v`
Expected: `AttributeError: 'JarvisBrain' object has no attribute 'system_prompt'`

- [ ] **Step 3: brain.py değişiklikleri**

`backend/core/brain.py:13-17` şu anki hali:

```python
class JarvisBrain:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.memory = ConversationMemory(max_turns=20)
        self.tools = self._define_tools()
```

şuna değiştir:

```python
class JarvisBrain:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.memory = ConversationMemory(max_turns=20)
        self.tools = self._define_tools()
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Çekirdek hafıza dosyalarını (karakter/hakkımda/ilgi alanları) oturum
        başında bir kez okuyup sistem promptuna ekler. Import'lar burada (metod
        içinde) yapılır ki testler backend.config.MEMORY_DIR'ı monkeypatch
        edebilsin (modül-üstü import bunu engeller)."""
        from backend.config import MEMORY_DIR
        from backend.core.long_term_memory import MemoryStore
        store = MemoryStore(MEMORY_DIR)
        memory_context = store.read_core_files()
        if memory_context.strip():
            return SYSTEM_PROMPT + "\n\n## Egemen hakkında bildiklerin:\n" + memory_context
        return SYSTEM_PROMPT
```

`backend/core/brain.py`'de `_define_tools()` içindeki `declarations` listesinin son elemanı `take_screenshot` bildirimidir (satır ~146-158), hemen ardından `]` ile liste kapanır (satır 159), `return [types.Tool(function_declarations=declarations)]` gelir (satır 160). `take_screenshot` bildirimiyle listeyi kapatan `]` arasına şunu ekle:

```python
            types.FunctionDeclaration(
                name="remember",
                description="Kullanıcı 'not al', 'unutma ki', 'hatırla' dediğinde kalıcı bir bilgiyi kaydeder.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "Hatırlanacak bilgi, kısa ve net"},
                        "category": {"type": "string",
                                    "description": "karakter-tercihler, hakkimda, ilgi-alanlarim veya yeni bir konu adı",
                                    "default": "hakkimda"}
                    },
                    "required": ["fact"]
                }
            ),
            types.FunctionDeclaration(
                name="add_todo",
                description="Yapılacaklar listesine bir madde ekler.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"item": {"type": "string", "description": "Eklenecek yapılacak iş"}},
                    "required": ["item"]
                }
            ),
            types.FunctionDeclaration(
                name="complete_todo",
                description="Yapılacaklar listesindeki bir maddeyi tamamlandı olarak işaretler.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"item": {"type": "string", "description": "Tamamlanan maddenin metni veya bir kısmı"}},
                    "required": ["item"]
                }
            ),
            types.FunctionDeclaration(
                name="list_todos",
                description="Yapılacaklar listesini okur ('listemde ne var' gibi sorularda).",
                parameters_json_schema={"type": "object", "properties": {}, "required": []}
            ),
            types.FunctionDeclaration(
                name="recall",
                description="Geçmiş konuşma özetlerinde arama yapar ('geçen hafta ne konuşmuştuk' gibi sorularda).",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Aranacak konu/anahtar kelime"}},
                    "required": ["query"]
                }
            ),
```

`backend/core/brain.py:182-189` (`think()` içindeki `config` oluşturma) şu anki hali:

```python
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=MAX_TOKENS,
            tools=self.tools,
            # Sesli asistanda gecikme kritik: modelin cevap öncesi "düşünme"
            # aşamasını kapat (birkaç saniye kazandırır)
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
```

`system_instruction=SYSTEM_PROMPT` satırını `system_instruction=self.system_prompt` yap (geri kalan aynı kalır).

- [ ] **Step 4: PASS doğrula + tüm testler**

Run: `./venv/Scripts/python.exe -m pytest -v`
Expected: hepsi passed

- [ ] **Step 5: Commit**

```bash
git add backend/core/brain.py tests/test_brain_memory.py
git commit -m "feat: sohbet beyni oturum başı çekirdek hafızayı okuyor

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Sunucu kablolaması (lifespan + disconnect/reset tetikleyicileri)

**Files:**
- Modify: `backend/server.py:37` (import satırı), `:50-86` (`lifespan`), `:220-224` (`reset` dalı), `:226-227` (`WebSocketDisconnect` except bloğu)
- Create: `scripts/test_memory_ws.py` (manuel entegrasyon scripti)

**Interfaces:**
- Consumes: `MemoryStore` (Task 1), `summarize_and_save` (Task 2), `backend.config.MEMORY_DIR`
- Produces: `app.state.memory_store`; `_save_session_memory(messages, store)` yardımcı fonksiyonu

- [ ] **Step 1: Import satırını güncelle**

`backend/server.py:37` şu anki hali:

```python
from backend.config import SERVER_HOST, SERVER_PORT, FOLLOWUP_WINDOW
```

şuna değiştir:

```python
from backend.config import SERVER_HOST, SERVER_PORT, FOLLOWUP_WINDOW, MEMORY_DIR
```

- [ ] **Step 2: lifespan'e MemoryStore ekle**

`backend/server.py:79-82` şu anki hali:

```python
    app.state.task_manager = TaskManager(event_cb=task_event)
    app.state.executor.task_manager = app.state.task_manager

    log.info("✅ Jarvis hazır! Bağlantı bekleniyor...")
```

şuna değiştir:

```python
    app.state.task_manager = TaskManager(event_cb=task_event)
    app.state.executor.task_manager = app.state.task_manager

    from backend.core.long_term_memory import MemoryStore
    app.state.memory_store = MemoryStore(MEMORY_DIR)
    app.state.executor.memory_store = app.state.memory_store

    log.info("✅ Jarvis hazır! Bağlantı bekleniyor...")
```

- [ ] **Step 3: reset dalına arka plan özetleme ekle**

`backend/server.py:220-224` şu anki hali:

```python
            # ── Hafıza sıfırlama ─────────────────────────────────────────────
            elif msg_type == "reset":
                brain.reset_memory()
                await manager.send(client_id, {"type": "status", "data": "reset"})
                log.info(f"🔄 [{client_id}] Hafıza sıfırlandı")
```

şuna değiştir:

```python
            # ── Hafıza sıfırlama ─────────────────────────────────────────────
            elif msg_type == "reset":
                # Sıfırlamadan ÖNCE anlık kopya al (get_messages() yeni bir liste
                # döndürür) — arka plan görevi çalışırken brain.memory temizlenmiş
                # olabilir, canlı referans yerine kopya kullanılır.
                messages_snapshot = brain.memory.get_messages()
                asyncio.create_task(_save_session_memory(messages_snapshot, app.state.memory_store))
                brain.reset_memory()
                await manager.send(client_id, {"type": "status", "data": "reset"})
                log.info(f"🔄 [{client_id}] Hafıza sıfırlandı")
```

- [ ] **Step 4: WebSocketDisconnect'e arka plan özetleme ekle**

`backend/server.py:226-227` şu anki hali:

```python
    except WebSocketDisconnect:
        manager.disconnect(client_id)
```

şuna değiştir:

```python
    except WebSocketDisconnect:
        manager.disconnect(client_id)
        messages_snapshot = brain.memory.get_messages()
        asyncio.create_task(_save_session_memory(messages_snapshot, app.state.memory_store))
```

- [ ] **Step 5: `_save_session_memory` yardımcı fonksiyonunu ekle**

`backend/server.py:210-217` civarındaki `_speak_short` fonksiyonunun HEMEN ÜSTÜNE (yani `async def _speak_short` satırından önce) ekle:

```python
async def _save_session_memory(messages: list, store):
    """Oturum bittiğinde (kopma/sıfırlama) arka planda konuşmayı özetler.
    Kendi try/except'i var — burada patlayan hiçbir şey sunucuyu etkilemez."""
    from backend.core.memory_digest import summarize_and_save
    try:
        await summarize_and_save(messages, store)
    except Exception as e:
        log.warning(f"Hafıza özetleme başarısız: {e}")


```

- [ ] **Step 6: Sözdizimi ve mevcut testleri doğrula**

Run: `./venv/Scripts/python.exe -m py_compile backend/server.py && ./venv/Scripts/python.exe -m pytest -v`
Expected: `py_compile` sessizce başarılı; pytest hepsi passed (server.py'nin kendi pytest testi yok, bu adım sadece regresyon yok diye kontrol)

- [ ] **Step 7: Manuel entegrasyon scripti** (`scripts/test_memory_ws.py`)

```python
"""Kalıcı hafıza websocket entegrasyon testi (sunucu açıkken çalıştır).
Kullanım: ./venv/Scripts/python.exe scripts/test_memory_ws.py
"""
import asyncio
import json
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import MEMORY_DIR


async def main():
    client_id = "pc-memory-test"
    async with websockets.connect(
        f"ws://localhost:8765/ws/{client_id}", max_size=10 * 1024 * 1024
    ) as ws:
        await ws.send(json.dumps({"type": "text", "data": "Not al: en sevdigim renk mavi."}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            print(msg["type"], ":", str(msg.get("data"))[:80])
            if msg["type"] == "status" and msg["data"] == "idle":
                break

        await ws.send(json.dumps({"type": "reset"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            print(msg["type"], ":", str(msg.get("data"))[:80])
            if msg["type"] == "status" and msg["data"] == "reset":
                break

    # reset arka plan özetleme görevini tetikler — tamamlanmasını bekle
    print("Arka plan özetleme bekleniyor (8sn)...")
    await asyncio.sleep(8)

    print("\nMEMORY_DIR:", MEMORY_DIR)
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.rglob("*.md")):
            print(" -", p.relative_to(MEMORY_DIR))
    else:
        print("UYARI: MEMORY_DIR henüz oluşmadı")


asyncio.run(main())
```

- [ ] **Step 8: Sunucuyu başlat ve entegrasyonu çalıştır**

Önce sunucu (ayrı terminal/arka plan, ffmpeg PATH'te olmalı):
`./venv/Scripts/python.exe -m backend.server`

Sunucu `/health` 200 dönene kadar bekle, sonra:
`./venv/Scripts/python.exe scripts/test_memory_ws.py`

Expected: `response` mesajında "kaydedildi" benzeri bir onay geçmeli (remember aracı çağrıldı); son çıktıda `MEMORY_DIR` altında en az `ilgi-alanlarim.md` (mavi rengi "not al" ile kaydedilen bilgi muhtemelen bu kategoriye ya da hakkimda'ya düşer — modelin seçimi) VE `digests/YYYY-MM-DD.md` listelenmeli. Dosyalardan birini `cat` ile aç, "mavi" geçtiğini doğrula.

Sunucuyu durdur (`Get-NetTCPConnection -LocalPort 8765 -State Listen | Stop-Process`).

- [ ] **Step 9: Commit**

```bash
git add backend/server.py scripts/test_memory_ws.py
git commit -m "feat: sunucu disconnect/reset olaylarında hafızayı arka planda özetliyor

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Canlı sesli test + dokümantasyon

**Files:**
- Modify: `README.md` (Özellikler tablosuna "Kalıcı hafıza (not alma, yapılacaklar, otomatik öğrenme) ✅" satırı; kısa kullanım örneği)
- Modify: `C:\Users\bozca\Documents\ObsidianVault\Projeler\Jarvis\Jarvis.md` ve `Yapılacaklar.md` (Faz 2 tamam işareti)

- [ ] **Step 1: Egemen'le canlı test**

Senaryolar (PC client veya web ile):
1. "Jarvis, not al: en sevdiğim dizi House." → onay cevabı gelmeli. Sonra "Jarvis, yapılacaklara ekle: markete git" → onay. "Jarvis, listemde ne var?" → "markete git" dönmeli.
2. Bağlantıyı kes/sıfırla (PC client'ı kapat-aç veya web'de sayfayı yenile) → birkaç saniye bekle → `MEMORY_DIR` altında yeni oturum için `digests/` dosyası oluştuğunu kontrol et.
3. Yeni bir oturumda (yeniden bağlan) "Jarvis, en sevdiğim dizi ne?" diye sor → önceki "not al" ile kaydedilen bilgiyi hatırlamalı (sistem promptuna oturum başı yüklendiği için).
4. "Jarvis, geçen konuşmamızda ne konuşmuştuk?" → `recall` aracını kullanıp digest'ten bir şeyler bulmalı.

- [ ] **Step 2: README güncelle**

Özellikler tablosuna ekle, "Görev Ajanı" bölümünün altına kısa bir "Kalıcı Hafıza" bölümü ekle (nasıl çalıştığını 2-3 cümleyle anlatan, `docs/superpowers/specs/2026-07-22-kalici-hafiza-design.md`'ye link veren).

- [ ] **Step 3: Obsidian vault güncelle**

`Yapılacaklar.md`'de Faz 2 satırını işaretle; `Jarvis.md`'ye kısa bir durum notu ekle (Faz 2 tamamlandı, MEMORY_DIR konumu).

- [ ] **Step 4: Final commit + push**

```bash
git add -A
git commit -m "feat: Kalıcı Hafıza Faz 2 tamamlandı (canlı sesli test geçti)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin kalici-hafiza
```

(Faz 1'de olduğu gibi merge işlemi ayrıca `main`'e yapılacak — final whole-branch review'dan sonra.)

---

## Self-Review Notları

- **Spec kapsaması:** Depolama (Task 1), otomatik özetleme + cömert prompt (Task 2), 5 açık araç (Task 3), oturum başı enjeksiyon (Task 4), disconnect/reset tetikleyicileri (Task 5), canlı test + dokümantasyon (Task 6). Konuşmacı ayrımı yok / embedding yok / budama yok / inaktivite zamanlayıcı yok — hepsi spec'in "kapsam dışı" bölümüyle uyumlu, plana hiç girmedi.
- **Placeholder taraması:** Yok — her adımda tam kod var.
- **Tip tutarlılığı:** `MemoryStore` metod imzaları Task 1'de tanımlanıp Task 3/4/5'te aynen kullanılıyor (`save_fact(category, text)`, `add_todo(item)`, `complete_todo(item)`, `read_todos()`, `search_digests(query)`, `read_core_files()`, `append_digest(text, when=None)`). `summarize_and_save(messages, store, generate_fn=None) -> bool` Task 2'de tanımlanıp Task 5'te aynen çağrılıyor. `messages` formatı (`{"role", "content"}` dict listesi) `ConversationMemory.get_messages()`'ın gerçek çıktısıyla eşleşiyor (Task 5'te `brain.memory.get_messages()` olarak besleniyor).
- **Kırılganlık notu:** Task 4'te `_build_system_prompt`'un import'ları metod içinde yapılması bilinçli — `backend.config.MEMORY_DIR`'ı test sırasında monkeypatch edebilmek için (modül-üstü `from ... import MEMORY_DIR` yapılsaydı monkeypatch işe yaramazdı). Bu, executor.py'deki `start_task`'ın zaten kullandığı aynı deseni takip ediyor.
