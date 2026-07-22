# Görev Ajanı (Faz 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jarvis'e arka planda çok adımlı iş yapan (araştırma+rapor, dosya işleri), riskli adımlarda sesli onay isteyen bir görev ajanı eklemek.

**Architecture:** Sohbet beyni (flash-lite) `start_task` aracıyla işi TaskManager'a devreder; TaskManager görevi asyncio.Task olarak TaskAgent'ta (gemini-3.5-flash) çalıştırır. Riskli araçlar onay Future'ında bekler; sunucu, onay beklenirken gelen konuşmayı önce onay filtresinden geçirir. Olaylar (başladı/onay/bitti/hata) sunucu üzerinden sesli duyurulur.

**Tech Stack:** Python 3.13 (mevcut venv), google-genai, FastAPI/WebSocket (mevcut), pytest + pytest-asyncio (yeni, sadece dev).

## Global Constraints

- Claude API/kotası KULLANILMAZ; tüm LLM çağrıları Gemini ücretsiz katmanı.
- Ajan modeli: `gemini-3.5-flash` (env: `AGENT_MODEL`); sohbet beyni `gemini-3.1-flash-lite` olarak KALIR.
- Adım limiti: 25. Onay zaman aşımı: 120 sn → RED (sessizlik asla onay değildir).
- Workspace: `~/Desktop/Jarvis-Workspace` (env: `JARVIS_WORKSPACE`); içine yazma serbest, dışına yazma/silme/taşıma/kopyalama ve `run_command` ONAYLI.
- Aynı anda tek görev (MVP). Görev sırasında sesli duyuru yalnızca: başlangıç, onay isteği, bitiş/hata.
- Testler gerçek Gemini'ye ÇIKMAZ (generate_fn enjeksiyonu); komutlar venv ile: `./venv/Scripts/python.exe -m pytest`.
- Türkçe kullanıcı metinleri; uzun tire (—) kullanma (Egemen tercihi, commit 35af3ef).

---

### Task 1: Test altyapısı + config sabitleri

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/__init__.py` (boş)
- Modify: `backend/config.py` (dosya sonuna ekle)

**Interfaces:**
- Produces: `backend.config.AGENT_MODEL: str`, `backend.config.WORKSPACE_DIR: pathlib.Path`, `backend.config.APPROVAL_TIMEOUT: float`

- [ ] **Step 1: requirements-dev.txt oluştur**

```
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

- [ ] **Step 2: Kur ve doğrula**

Run: `./venv/Scripts/python.exe -m pip install -r requirements-dev.txt --quiet && ./venv/Scripts/python.exe -m pytest --version`
Expected: `pytest 8.x` sürüm çıktısı

- [ ] **Step 3: Boş tests/__init__.py oluştur, config.py sonuna ekle**

```python
# ─── Görev Ajanı ────────────────────────────────────────────────────────────
from pathlib import Path

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-3.5-flash")  # görev ajanı (sohbet: GEMINI_MODEL)
WORKSPACE_DIR = Path(os.getenv("JARVIS_WORKSPACE",
                               str(Path.home() / "Desktop" / "Jarvis-Workspace")))
APPROVAL_TIMEOUT = float(os.getenv("APPROVAL_TIMEOUT", "120"))  # sn; dolarsa RED
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "25"))
```

- [ ] **Step 4: Import doğrula**

Run: `./venv/Scripts/python.exe -c "from backend.config import AGENT_MODEL, WORKSPACE_DIR, APPROVAL_TIMEOUT, AGENT_MAX_STEPS; print(AGENT_MODEL, WORKSPACE_DIR)"`
Expected: `gemini-3.5-flash C:\Users\bozca\Desktop\Jarvis-Workspace`

- [ ] **Step 5: Commit**

```bash
git add requirements-dev.txt tests/__init__.py backend/config.py
git commit -m "feat: görev ajanı config sabitleri ve test altyapısı"
```

---

### Task 2: FileTools + riskli işlem sınıflandırması

**Files:**
- Create: `backend/skills/file_tools.py`
- Test: `tests/test_file_tools.py`

**Interfaces:**
- Consumes: `backend.config.WORKSPACE_DIR` (varsayılan olarak)
- Produces:
  - `FileTools(workspace: Path)` — metodlar: `list_dir(path: str = "") -> str`, `read_file(path: str) -> str`, `write_file(path: str, content: str) -> str`, `delete_path(path: str) -> str`, `move_path(src: str, dst: str) -> str`, `copy_path(src: str, dst: str) -> str`. Tüm path'ler: göreliyse workspace'e göre, mutlak da olabilir. Kurucu workspace klasörünü oluşturur.
  - `requires_approval(tool_name: str, args: dict, workspace: Path) -> tuple[bool, str]` — (onay gerekli mi, insan-okur eylem açıklaması)

- [ ] **Step 1: Failing testleri yaz** (`tests/test_file_tools.py`)

```python
from pathlib import Path
from backend.skills.file_tools import FileTools, requires_approval


def test_write_and_read_inside_workspace(tmp_path):
    ft = FileTools(workspace=tmp_path)
    msg = ft.write_file("rapor.md", "# Merhaba")
    assert "rapor.md" in msg
    assert ft.read_file("rapor.md") == "# Merhaba"
    assert "rapor.md" in ft.list_dir("")


def test_workspace_created_on_init(tmp_path):
    ws = tmp_path / "yeni-workspace"
    FileTools(workspace=ws)
    assert ws.is_dir()


def test_read_missing_file_returns_error_text(tmp_path):
    ft = FileTools(workspace=tmp_path)
    assert "bulunamadı" in ft.read_file("yok.txt")


def test_delete_and_move_work(tmp_path):
    ft = FileTools(workspace=tmp_path)
    ft.write_file("a.txt", "x")
    ft.move_path("a.txt", "b.txt")
    assert (tmp_path / "b.txt").exists() and not (tmp_path / "a.txt").exists()
    ft.delete_path("b.txt")
    assert not (tmp_path / "b.txt").exists()


def test_approval_rules(tmp_path):
    ws = tmp_path
    ok, _ = requires_approval("read_file", {"path": "x.txt"}, ws)
    assert ok is False
    ok, _ = requires_approval("list_dir", {"path": ""}, ws)
    assert ok is False
    ok, _ = requires_approval("write_file", {"path": "rapor.md", "content": ""}, ws)
    assert ok is False  # workspace içi yazma serbest
    ok, desc = requires_approval("write_file", {"path": str(Path.home() / "x.txt"), "content": ""}, ws)
    assert ok is True and "x.txt" in desc  # workspace dışı yazma onaylı
    for tool in ("delete_path", "move_path", "copy_path", "run_command"):
        ok, _ = requires_approval(tool, {"path": "ws-ici.txt", "src": "a", "dst": "b", "command": "dir"}, ws)
        assert ok is True  # her zaman onaylı
```

- [ ] **Step 2: Testlerin FAIL ettiğini doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_file_tools.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.skills.file_tools'`

- [ ] **Step 3: Implementasyon** (`backend/skills/file_tools.py`)

```python
"""
Görev ajanının dosya araçları + riskli işlem sınıflandırması.
Kural: workspace içine yazma serbest; workspace dışına yazma, her türlü
silme/taşıma/kopyalama ve run_command ONAY ister (spec: 2026-07-22).
"""
import shutil
from pathlib import Path

READ_LIMIT = 50_000  # karakter; uzun dosyalar kırpılır

ALWAYS_APPROVAL = {"delete_path", "move_path", "copy_path", "run_command"}


class FileTools:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    def list_dir(self, path: str = "") -> str:
        p = self._resolve(path)
        if not p.is_dir():
            return f"Klasör bulunamadı: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'[D]' if e.is_dir() else '[F]'} {e.name}" for e in entries]
        return "\n".join(lines) or "(boş klasör)"

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"Dosya bulunamadı: {p}"
        text = p.read_text(encoding="utf-8", errors="ignore")
        if len(text) > READ_LIMIT:
            return text[:READ_LIMIT] + f"\n... (kırpıldı, toplam {len(text)} karakter)"
        return text

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Yazıldı: {p} ({len(content)} karakter)"

    def delete_path(self, path: str) -> str:
        p = self._resolve(path)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
        else:
            return f"Zaten yok: {p}"
        return f"Silindi: {p}"

    def move_path(self, src: str, dst: str) -> str:
        s, d = self._resolve(src), self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"Taşındı: {s} -> {d}"

    def copy_path(self, src: str, dst: str) -> str:
        s, d = self._resolve(src), self._resolve(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return f"Kopyalandı: {s} -> {d}"


def requires_approval(tool_name: str, args: dict, workspace: Path) -> tuple[bool, str]:
    """(onay_gerekli_mi, insan-okur eylem açıklaması) döndürür."""
    workspace = Path(workspace).resolve()

    if tool_name in ALWAYS_APPROVAL:
        if tool_name == "run_command":
            return True, f"şu komutu çalıştıracağım: {args.get('command', '?')}"
        if tool_name == "delete_path":
            return True, f"şunu sileceğim: {args.get('path', '?')}"
        if tool_name == "move_path":
            return True, f"şunu taşıyacağım: {args.get('src', '?')} -> {args.get('dst', '?')}"
        return True, f"şunu kopyalayacağım: {args.get('src', '?')} -> {args.get('dst', '?')}"

    if tool_name == "write_file":
        p = Path(args.get("path", ""))
        if not p.is_absolute():
            return False, ""
        try:
            p.resolve().relative_to(workspace)
            return False, ""
        except ValueError:
            return True, f"workspace dışına dosya yazacağım: {p}"

    return False, ""
```

- [ ] **Step 4: Testlerin PASS ettiğini doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_file_tools.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/skills/file_tools.py tests/test_file_tools.py
git commit -m "feat: FileTools ve riskli işlem sınıflandırması"
```

---

### Task 3: Onay cümlesi ayrıştırıcı (parse_approval)

**Files:**
- Create: `backend/core/task_manager.py` (bu görevde yalnızca parse_approval)
- Test: `tests/test_approval.py`

**Interfaces:**
- Produces: `parse_approval(text: str) -> bool | None` — True=onay, False=red, None=alakasız konuşma

- [ ] **Step 1: Failing testleri yaz** (`tests/test_approval.py`)

```python
import pytest
from backend.core.task_manager import parse_approval


@pytest.mark.parametrize("text", ["evet", "Evet.", "onayla", "onaylıyorum", "yap", "tamam", "evet yap lütfen"])
def test_approvals(text):
    assert parse_approval(text) is True


@pytest.mark.parametrize("text", ["hayır", "Hayır!", "iptal", "yapma", "dur", "hayır iptal et"])
def test_rejections(text):
    assert parse_approval(text) is False


@pytest.mark.parametrize("text", ["saat kaç", "hava nasıl bugün", "", "raporu sonra okurum"])
def test_unrelated(text):
    assert parse_approval(text) is None


def test_rejection_wins_when_both():
    # "yapma" içinde "yap" geçer; kelime bazlı eşleşme bunu RED saymalı
    assert parse_approval("yapma") is False
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_approval.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.core.task_manager'`

- [ ] **Step 3: Implementasyon** (`backend/core/task_manager.py` başlangıcı)

```python
"""
TaskManager: görev yaşam döngüsü + sesli onay akışı.
Spec: docs/superpowers/specs/2026-07-22-gorev-ajani-design.md
"""
import re

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
```

- [ ] **Step 4: PASS doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_approval.py -v`
Expected: 18 passed (7 onay + 6 red + 4 alakasız + 1 çelişki testi)

- [ ] **Step 5: Commit**

```bash
git add backend/core/task_manager.py tests/test_approval.py
git commit -m "feat: sesli onay cümlesi ayrıştırıcı (parse_approval)"
```

---

### Task 4: TaskManager (durum makinesi + onay Future'ı)

**Files:**
- Modify: `backend/core/task_manager.py` (parse_approval'ın altına ekle)
- Test: `tests/test_task_manager.py`

**Interfaces:**
- Consumes: `parse_approval` (Task 3)
- Produces:
  ```python
  class TaskState(str, Enum): RUNNING; WAITING_APPROVAL; DONE; FAILED

  class TaskManager:
      def __init__(self, event_cb: Callable[[str, str], Awaitable[None]],
                   approval_timeout: float = APPROVAL_TIMEOUT)
      # event_cb(event_type, message); event_type in:
      # "started" | "approval_request" | "done" | "failed"
      def start(self, description: str, runner: Callable[["TaskManager"], Awaitable[str]]) -> str
      # runner: görevi yürüten coroutine factory (gerçekte TaskAgent.run, testte sahte)
      # dönen str: kullanıcıya söylenecek anlık yanıt ("Başlıyorum" / "zaten görev var")
      def status_text(self) -> str
      @property
      def waiting_approval(self) -> bool
      async def request_approval(self, action_desc: str) -> bool   # ajan çağırır, bekler
      async def handle_utterance(self, text: str) -> str | None
      # onay yakaladıysa kullanıcıya söylenecek kısa yanıt, değilse None
  ```

- [ ] **Step 1: Failing testleri yaz** (`tests/test_task_manager.py`)

```python
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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_task_manager.py -v`
Expected: `ImportError: cannot import name 'TaskManager'`

- [ ] **Step 3: Implementasyon** (task_manager.py'ye ekle; dosya başındaki importları güncelle)

```python
import asyncio
from enum import Enum
from typing import Awaitable, Callable

from backend.config import APPROVAL_TIMEOUT


class TaskState(str, Enum):
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

    # ── yaşam döngüsü ──
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

    # ── onay akışı ──
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
        from backend.core.task_manager import parse_approval  # aynı modül; netlik için
        verdict = parse_approval(text)
        if verdict is None:
            return None
        self._approval_future.set_result(verdict)
        return "Anlaşıldı, devam ediyorum." if verdict else "Anlaşıldı, o adımı iptal ediyorum."
```

Not: `pytest.ini` yerine `pytest-asyncio` mod ayarı gerekir; repo köküne `pytest.ini` ekle:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: PASS doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_task_manager.py tests/test_approval.py -v`
Expected: hepsi passed

- [ ] **Step 5: Commit**

```bash
git add backend/core/task_manager.py tests/test_task_manager.py pytest.ini
git commit -m "feat: TaskManager durum makinesi ve onay Future akışı"
```

---

### Task 5: TaskAgent (çok adımlı ajan döngüsü)

**Files:**
- Create: `backend/core/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `FileTools`, `requires_approval` (Task 2); `TaskManager.request_approval` (Task 4, approval_cb olarak); `SkillExecutor.web_search`, `SkillExecutor.run_command` (mevcut)
- Produces:
  ```python
  class TaskAgent:
      def __init__(self, description: str, file_tools: FileTools,
                   executor,                      # SkillExecutor (web_search/run_command için)
                   approval_cb: Callable[[str], Awaitable[bool]],
                   generate_fn: Callable | None = None,  # None ise gerçek Gemini
                   max_steps: int = AGENT_MAX_STEPS)
      async def run(self) -> str    # sesli özet döndürür
  ```
  `generate_fn(contents: list) -> response` async; response google-genai yanıtı gibi
  `.candidates[0].content.parts` taşımalı (testte sahte nesne).

- [ ] **Step 1: Failing testleri yaz** (`tests/test_agent.py`)

```python
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


async def reject_all(desc):
    return False


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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_agent.py -v`
Expected: `ModuleNotFoundError: No module named 'backend.core.agent'`

- [ ] **Step 3: Implementasyon** (`backend/core/agent.py`)

```python
"""
TaskAgent: arka planda çok adımlı görev yürüten ajan.
Sohbet beyninden bağımsız, daha güçlü model (AGENT_MODEL) kullanır.
Spec: docs/superpowers/specs/2026-07-22-gorev-ajani-design.md
"""
import asyncio

from backend.config import AGENT_MODEL, AGENT_MAX_STEPS, GEMINI_API_KEY
from backend.skills.file_tools import FileTools, requires_approval

AGENT_SYSTEM_PROMPT = """Sen Jarvis'in görev ajanısın. Sana verilen işi araçlarınla
adım adım, baştan sona bitir.

Kurallar:
- Ürettiğin raporları/dosyaları workspace'e yaz (write_file, göreli yol yeter).
- Araştırma işlerinde web_search kullan; birden fazla arama yapabilirsin.
- Riskli adımlar kullanıcı onayından geçer; RED gelirse o adımı atla, işi
  elindekiyle bitir ve durumu son özetinde belirt.
- İş bitince SON mesajın kullanıcıya SESLİ okunacak kısa bir Türkçe özet olsun
  (2-3 cümle): ne yaptın, çıktı nerede.
"""

RETRY_DELAYS = [5, 15, 30]  # sn; 429/503 için


class TaskAgent:
    def __init__(self, description, file_tools: FileTools, executor,
                 approval_cb, generate_fn=None, max_steps: int = AGENT_MAX_STEPS):
        self.description = description
        self.ft = file_tools
        self.executor = executor
        self.approval_cb = approval_cb
        self.max_steps = max_steps
        self._generate = generate_fn or self._real_generate
        self._contents = []  # sözlük listesi (role/parts) yerine SDK Content'leri

    # ── gerçek Gemini (generate_fn verilmediyse) ──
    async def _real_generate(self, contents):
        from google import genai
        from google.genai import types
        if not hasattr(self, "_client"):
            self._client = genai.Client(api_key=GEMINI_API_KEY)
        config = types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM_PROMPT + f"\nWorkspace: {self.ft.workspace}",
            tools=[types.Tool(function_declarations=self._declarations())],
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        return await self._client.aio.models.generate_content(
            model=AGENT_MODEL, contents=contents, config=config)

    @staticmethod
    def _declarations():
        from google.genai import types
        schema = lambda props, req: {"type": "object", "properties": props, "required": req}
        s = {"type": "string"}
        return [
            types.FunctionDeclaration(name="list_dir", description="Klasör içeriğini listeler",
                parameters_json_schema=schema({"path": s}, [])),
            types.FunctionDeclaration(name="read_file", description="Dosya okur",
                parameters_json_schema=schema({"path": s}, ["path"])),
            types.FunctionDeclaration(name="write_file", description="Dosya yazar (workspace'e göreli yol serbest)",
                parameters_json_schema=schema({"path": s, "content": s}, ["path", "content"])),
            types.FunctionDeclaration(name="delete_path", description="Dosya/klasör siler (onay ister)",
                parameters_json_schema=schema({"path": s}, ["path"])),
            types.FunctionDeclaration(name="move_path", description="Taşır (onay ister)",
                parameters_json_schema=schema({"src": s, "dst": s}, ["src", "dst"])),
            types.FunctionDeclaration(name="copy_path", description="Kopyalar (onay ister)",
                parameters_json_schema=schema({"src": s, "dst": s}, ["src", "dst"])),
            types.FunctionDeclaration(name="run_command", description="PowerShell komutu (onay ister)",
                parameters_json_schema=schema({"command": s}, ["command"])),
            types.FunctionDeclaration(name="web_search", description="Web'de araştırır",
                parameters_json_schema=schema({"query": s}, ["query"])),
        ]

    # ── araç yürütme ──
    async def _exec_tool(self, name: str, args: dict) -> str:
        needs, desc = requires_approval(name, args, self.ft.workspace)
        if needs:
            approved = await self.approval_cb(desc)
            if not approved:
                return "Kullanıcı bu adımı REDDETTİ. Adımı atla, işi elindekiyle sürdür."
        try:
            if name == "list_dir":
                return self.ft.list_dir(args.get("path", ""))
            if name == "read_file":
                return self.ft.read_file(args["path"])
            if name == "write_file":
                return self.ft.write_file(args["path"], args["content"])
            if name == "delete_path":
                return self.ft.delete_path(args["path"])
            if name == "move_path":
                return self.ft.move_path(args["src"], args["dst"])
            if name == "copy_path":
                return self.ft.copy_path(args["src"], args["dst"])
            if name == "run_command":
                return await self.executor.run_command(args["command"])
            if name == "web_search":
                return await self.executor.web_search(args["query"])
            return f"Bilinmeyen araç: {name}"
        except Exception as e:
            return f"Araç hatası ({name}): {e}"

    async def _generate_with_retry(self, contents):
        last = None
        for delay in [0] + RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._generate(contents)
            except Exception as e:
                last = e
                if not any(code in str(e) for code in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                    raise
        raise last

    # ── ana döngü ──
    async def run(self) -> str:
        from google.genai import types
        contents = [types.Content(role="user", parts=[types.Part(text=f"Görev: {self.description}")])]

        for step in range(self.max_steps + 1):
            if step == self.max_steps:
                contents.append(types.Content(role="user", parts=[types.Part(
                    text="Adım limitine ulaştın. Yeni araç çağırma; elindekiyle kısa sesli özetini ver.")]))
            response = await self._generate_with_retry(contents)
            parts = response.candidates[0].content.parts or []
            fcs = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not fcs or step == self.max_steps:
                return (getattr(response, "text", "") or "Görev tamamlandı.").strip()

            contents.append(types.Content(role="model", parts=list(parts)))
            results = []
            for fc in fcs:
                args = dict(fc.args) if fc.args else {}
                print(f"🤖🔧 Ajan aracı: {fc.name} -> {args}")
                out = await self._exec_tool(fc.name, args)
                results.append(types.Part.from_function_response(
                    name=fc.name, response={"result": str(out)[:8000]}))
            contents.append(types.Content(role="user", parts=results))
        return "Görev tamamlandı."
```

Not (test uyumu): testlerdeki FakePart/FakeFC gerçek SDK tipleri değildir; `run()`
içindeki `types.Content(...)` sarmalamaları sahte parçalarla da çalışır çünkü
Content.parts herhangi bir nesne listesi kabul eder ve `_generate` sahte olduğunda
içerik Gemini'ye gitmez. `p.function_call` erişimi `getattr` ile korunur.

- [ ] **Step 4: PASS doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_agent.py -v`
Expected: 4 passed. (types.Content sahte Part kabul etmezse: contents'i düz liste
`[{"role":..., "parts":[...]}]` tut ve _real_generate içinde SDK tipine çevir;
testler yalnızca davranışı doğrular.)

- [ ] **Step 5: Tüm testleri çalıştır ve commit**

Run: `./venv/Scripts/python.exe -m pytest -v`
Expected: hepsi passed

```bash
git add backend/core/agent.py tests/test_agent.py
git commit -m "feat: TaskAgent çok adımlı ajan döngüsü (onay, retry, adım limiti)"
```

---

### Task 6: Sohbet beynine start_task/task_status bağlama

**Files:**
- Modify: `backend/skills/executor.py` (SkillExecutor.__init__ ve handlers)
- Modify: `backend/core/brain.py` (_define_tools'a 2 bildirim)
- Test: `tests/test_executor_task_tools.py`

**Interfaces:**
- Consumes: `TaskManager.start`, `TaskManager.status_text` (Task 4); `TaskAgent` (Task 5)
- Produces: `SkillExecutor.task_manager` attribute (sunucu set eder);
  `start_task(description: str) -> str`, `task_status() -> str` araçları

- [ ] **Step 1: Failing test yaz** (`tests/test_executor_task_tools.py`)

```python
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
```

- [ ] **Step 2: FAIL doğrula**

Run: `./venv/Scripts/python.exe -m pytest tests/test_executor_task_tools.py -v`
Expected: `Bilinmeyen araç: start_task` assert hatası

- [ ] **Step 3: executor.py değişiklikleri**

`__init__`e ekle:

```python
        self.task_manager = None   # server.py lifespan'de set edilir
```

`handlers` sözlüğüne ekle:

```python
            "start_task": self.start_task,
            "task_status": self.task_status,
```

Sınıfa metodları ekle (web_search'ün üstüne):

```python
    # ─── Görev Ajanı köprüsü ─────────────────────────────────────────────────
    async def start_task(self, description: str) -> str:
        if self.task_manager is None:
            return "Görev sistemi henüz hazır değil."
        from backend.config import WORKSPACE_DIR
        from backend.core.agent import TaskAgent
        from backend.skills.file_tools import FileTools

        def runner_factory(tm):
            agent = TaskAgent(description, FileTools(WORKSPACE_DIR), executor=self,
                              approval_cb=tm.request_approval)
            return agent.run()

        return self.task_manager.start(description, runner_factory)

    async def task_status(self) -> str:
        if self.task_manager is None:
            return "Görev sistemi henüz hazır değil."
        return self.task_manager.status_text()
```

- [ ] **Step 4: brain.py bildirimleri** (_define_tools listesine, web_search'ten sonra)

```python
            types.FunctionDeclaration(
                name="start_task",
                description=(
                    "Çok adımlı bir işi arka plan görev ajanına devreder: araştırma+rapor, "
                    "dosya/klasör düzenleme, özet çıkarma gibi. Kullanıcı bir 'iş' istediğinde "
                    "bunu kullan; basit soru-cevap için KULLANMA. Dönen mesajı kullanıcıya aynen söyle."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "description": {"type": "string",
                                        "description": "Görevin tam tanımı, kullanıcının isteğindeki tüm detaylarla"}
                    },
                    "required": ["description"]
                }
            ),
            types.FunctionDeclaration(
                name="task_status",
                description="Arka plandaki görevin durumunu sorar ('görev ne durumda' gibi sorularda).",
                parameters_json_schema={"type": "object", "properties": {}, "required": []}
            ),
```

- [ ] **Step 5: PASS doğrula + tüm testler**

Run: `./venv/Scripts/python.exe -m pytest -v`
Expected: hepsi passed

- [ ] **Step 6: Commit**

```bash
git add backend/skills/executor.py backend/core/brain.py tests/test_executor_task_tools.py
git commit -m "feat: sohbet beynine start_task/task_status araçları"
```

---

### Task 7: Sunucu kablolaması (olay duyuruları + onay yakalama)

**Files:**
- Modify: `backend/server.py`
- Create: `scripts/test_task_ws.py` (manuel entegrasyon scripti)

**Interfaces:**
- Consumes: `TaskManager` (Task 4), `SkillExecutor.task_manager` (Task 6)
- Produces: WS mesajı `{"type": "task_update", "data": {"event": ..., "message": ...}}`;
  onay yakalama hem audio hem text yolunda çalışır

- [ ] **Step 1: lifespan'e TaskManager ekle** (server.py, `app.state.executor = SkillExecutor()` satırından sonra)

```python
    from backend.core.task_manager import TaskManager

    async def task_event(event_type: str, message: str):
        """Görev olaylarını tüm clientlara duyur + sesli oku."""
        await manager.broadcast({"type": "task_update",
                                 "data": {"event": event_type, "message": message}})
        speech = {
            "started": f"Görev alındı: {message}",
            "approval_request": f"Onayına ihtiyacım var efendim: {message}. Onaylıyor musun?",
            "done": message,
            "failed": message,
        }.get(event_type)
        if speech:
            await manager.broadcast({"type": "response", "data": speech})
            sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", speech) if s.strip()] or [speech]
            for sentence in sentences:
                audio_bytes = await app.state.tts.synthesize(sentence)
                await manager.broadcast({"type": "audio",
                                         "data": base64.b64encode(audio_bytes).decode()})

    app.state.task_manager = TaskManager(event_cb=task_event)
    app.state.executor.task_manager = app.state.task_manager
```

- [ ] **Step 2: Onay yakalamayı iki giriş yoluna ekle**

Audio dalında, `await manager.send(client_id, {"type": "transcript", ...})` satırından SONRA,
`_process_message` çağrısından ÖNCE:

```python
                tm = app.state.task_manager
                if tm.waiting_approval:
                    ack = await tm.handle_utterance(transcript)
                    if ack:
                        await _speak_short(client_id, ack)
                        continue
```

Text dalında, `await _process_message(...)` çağrısından ÖNCE aynısı (`transcript` yerine `text`).

Dosyaya yardımcı fonksiyon ekle (_process_message'ın üstüne):

```python
async def _speak_short(client_id: str, text: str):
    """Kısa onay yanıtı: metin + tek parça ses."""
    await manager.send(client_id, {"type": "response", "data": text})
    tts: TextToSpeech = app.state.tts
    audio_bytes = await tts.synthesize(text)
    await manager.send(client_id, {"type": "audio",
                                   "data": base64.b64encode(audio_bytes).decode()})
    await manager.send(client_id, {"type": "status", "data": "idle"})
```

- [ ] **Step 3: Manuel entegrasyon scripti** (`scripts/test_task_ws.py`)

```python
"""Görev ajanı websocket entegrasyon testi (sunucu açıkken çalıştır).
Kullanım: ./venv/Scripts/python.exe scripts/test_task_ws.py
"""
import asyncio, json, sys
import websockets


async def main():
    async with websockets.connect("ws://localhost:8765/ws/task-test",
                                  max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "text",
            "data": "Görev: workspace'e deneme.txt adında icinde 'merhaba' yazan bir dosya olustur."}))
        seen = []
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            if msg["type"] == "task_update":
                seen.append(msg["data"]["event"])
                print("OLAY:", msg["data"]["event"], "|", msg["data"]["message"][:80])
                if msg["data"]["event"] in ("done", "failed"):
                    break
            elif msg["type"] == "response":
                print("YANIT:", msg["data"][:80])
    print("Olay sirasi:", seen)
    assert seen[0] == "started" and seen[-1] == "done", "Olay sirasi hatali!"
    print("ENTEGRASYON OK")

asyncio.run(main())
```

- [ ] **Step 4: Entegrasyonu çalıştır**

Önce sunucu: `./venv/Scripts/python.exe -m backend.server` (ayrı terminal/arka plan)
Sonra: `./venv/Scripts/python.exe scripts/test_task_ws.py`
Expected: `OLAY: started`, `OLAY: done`, `ENTEGRASYON OK` ve
`Masaüstü/Jarvis-Workspace/deneme.txt` içeriği "merhaba" olmalı. Doğrula:
`cat ~/Desktop/Jarvis-Workspace/deneme.txt`

- [ ] **Step 5: Onaylı senaryoyu manuel test et**

Sunucu açıkken text modda ("scripts/start_text_mode.bat" veya ws scriptini uyarlayıp):
"Görev: masaüstündeki deneme-onay.txt dosyasını oluştur" (workspace DIŞI yol) →
`approval_request` olayı gelmeli → "evet" gönder → görev `done` olmalı ve dosya
masaüstünde olmalı. RED senaryosu: "hayır" → dosya oluşmamalı, görev yine `done`
(adımı atlayarak bitirmeli).

- [ ] **Step 6: Commit**

```bash
git add backend/server.py scripts/test_task_ws.py
git commit -m "feat: görev olay duyuruları ve sesli onay yakalama (server)"
```

---

### Task 8: Canlı sesli doğrulama + dokümantasyon

**Files:**
- Modify: `README.md` (Özellikler tablosuna "Arka plan görev ajanı ✅" satırı; "Yeni Yetenek Eklemek" bölümüne görev ajanı notu)
- Modify: `C:\Users\bozca\Documents\ObsidianVault\Projeler\Jarvis\Jarvis.md` ve `Yapılacaklar.md` (Faz 1 tamam işareti)

- [ ] **Step 1: Egemen'le canlı sesli test**

Senaryolar (PC client ile):
1. "Jarvis, dinozorların nesli neden tükendi, webde araştırıp masaüstündeki klasöre rapor yaz" → anında "Başlıyorum" duyulmalı; görev sürerken "Jarvis, saat kaç" normal cevaplanmalı; bitince sesli özet + workspace'te rapor dosyası.
2. Onay senaryosu: "Jarvis, workspace'teki raporu masaüstüne taşı" → sesli onay sorusu → "evet" → taşınmalı.
3. RED senaryosu: benzer istek → "hayır" → taşınmamalı, Jarvis durumu söylemeli.

- [ ] **Step 2: README güncelle** (özellik satırı + kısa kullanım örneği)

- [ ] **Step 3: Obsidian vault güncelle** (Yapılacaklar: Faz 1 işaretle; Jarvis.md: durum notu)

- [ ] **Step 4: Final commit + push**

```bash
git add -A
git commit -m "feat: Görev Ajanı Faz 1 tamamlandı (canlı sesli test geçti)"
git push
```

---

## Self-Review Notları

- Spec kapsaması: TaskAgent (T5), TaskManager (T4), sohbet araçları (T6), onay akışı (T3/T4/T7), workspace (T2), 429/503 backoff (T5), olay duyuruları (T7), test planındaki üç seviye (birim T2-T6, entegrasyon T7, canlı T8). Konuşmacı tanıma bilinçli kapsam dışı.
- Tip tutarlılığı: `runner` imzası T4'te `Callable[[TaskManager], Awaitable[str]]`; T6'daki `runner_factory(tm)` bir coroutine döndürür — TaskManager.start bunu `create_task(self._run(runner))` ile değil `runner(self)` çağrısıyla bekler; T4 implementasyonunda `_run` içinde `await runner(self)` var, T6 fabrikası `agent.run()` coroutine'ini döndürdüğü için `runner(tm)` çağrısı coroutine üretir ve await edilir. Uyumlu.
- Kırılganlık notu: T5 Step 4'te sahte Part'lar `types.Content` ile uyuşmazsa düz-liste fallback'i tarif edildi.
