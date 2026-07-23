# Proaktiflik (Faz 3) — Uygulama Planı

Spec: `docs/superpowers/specs/2026-07-23-proaktiflik-design.md`
Branch: `proaktiflik` (main'den)
Süreç: subagent-driven — her task için taze bir implementer subagent + bir task reviewer subagent, sonra final whole-branch review (fable).

## Task 1: ReminderStore (`backend/core/reminders.py`)

Faz 2'nin `MemoryStore` (`backend/core/long_term_memory.py`) deseniyle aynı: JSON dosya tabanlı, `MEMORY_DIR/reminders.json`.

```python
"""
Kalıcı hatırlatıcı deposu ve sabah bröfingi durumu. JSON dosyada tutulur,
repo dışında (backend.config.MEMORY_DIR). Sunucu kapansa/yeniden başlasa
bile hatırlatıcılar ve "bugün bröfing yapıldı mı" bilgisi kaybolmaz.
Spec: docs/superpowers/specs/2026-07-23-proaktiflik-design.md
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path


class ReminderStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.base_dir / "reminders.json"

    def _read(self) -> dict:
        if not self._path.exists():
            return {"reminders": [], "last_briefing_date": None}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"reminders": [], "last_briefing_date": None}

    def _write(self, data: dict):
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, message: str, fire_at: datetime, recurrence: str | None = None) -> str:
        data = self._read()
        data["reminders"].append({
            "id": str(uuid.uuid4()),
            "message": message,
            "fire_at": fire_at.isoformat(),
            "recurrence": recurrence,
            "done": False,
        })
        self._write(data)
        when = f"her gün {fire_at.strftime('%H:%M')}" if recurrence else fire_at.strftime("%d.%m %H:%M")
        return f"✅ Hatırlatıcı kuruldu ({when}): '{message}'"

    def due(self, now: datetime) -> list[dict]:
        data = self._read()
        return [r for r in data["reminders"]
                if not r["done"] and datetime.fromisoformat(r["fire_at"]) <= now]

    def mark_fired(self, reminder_id: str):
        data = self._read()
        for r in data["reminders"]:
            if r["id"] == reminder_id:
                if r["recurrence"] == "daily":
                    next_fire = datetime.fromisoformat(r["fire_at"]) + timedelta(days=1)
                    r["fire_at"] = next_fire.isoformat()
                else:
                    r["done"] = True
                break
        self._write(data)

    def list_active(self) -> str:
        data = self._read()
        active = [r for r in data["reminders"] if not r["done"]]
        if not active:
            return "Aktif hatırlatıcı yok."
        lines = []
        for r in active:
            when = datetime.fromisoformat(r["fire_at"]).strftime("%d.%m %H:%M")
            tag = " (her gün tekrarlar)" if r["recurrence"] == "daily" else ""
            lines.append(f"- {r['message']} — {when}{tag}")
        return "\n".join(lines)

    def cancel(self, query: str) -> str:
        data = self._read()
        query_lower = query.lower()
        for r in data["reminders"]:
            if not r["done"] and query_lower in r["message"].lower():
                r["done"] = True
                self._write(data)
                return f"İptal edildi: {r['message']}"
        return f"'{query}' ile eşleşen aktif hatırlatıcı bulunamadı."

    def get_last_briefing_date(self) -> str | None:
        return self._read().get("last_briefing_date")

    def set_last_briefing_date(self, date_str: str):
        data = self._read()
        data["last_briefing_date"] = date_str
        self._write(data)
```

**Testler** (`tests/test_reminders.py`, `tmp_path` kullan, gerçek saat BEKLENMEZ — `now` her zaman açık parametre):
- `add()` + `due()`: geçmiş `fire_at` due listesinde, gelecekteki değil
- `mark_fired()` tek seferlik: `done=True` olur, bir daha `due()`'da çıkmaz
- `mark_fired()` `recurrence="daily"`: `fire_at` +1 gün ileri alınır, ertesi gün tekrar `due()`'da çıkar
- `list_active()`: boşken "Aktif hatırlatıcı yok.", doluyken mesaj+saat içerir
- `cancel()`: kısmi metin eşleşmesiyle iptal eder (case-insensitive), eşleşme yoksa "bulunamadı" döner
- Bozuk `reminders.json` (elle bozuk metin yazılmış dosya) → çökmeden boş depo gibi davranır
- `get_last_briefing_date`/`set_last_briefing_date` round-trip, ilk hal `None`

Faz 2'nin `test_long_term_memory.py`'sindeki stil ve testleri birebir örnek al.

## Task 2: Sabah bröfingi üretimi (`backend/core/briefing.py`)

`memory_digest.py`'deki `generate_fn` dependency-injection desenini birebir kullan (test edilebilirlik için).

```python
"""
Sabah bröfingi: PC client'ın günün ilk bağlantısında hava durumu, açık
yapılacaklar ve son günlerin özetinden doğal bir takip sorusu içeren
kısa, sesli okunacak bir metin üretir.
Spec: docs/superpowers/specs/2026-07-23-proaktiflik-design.md
"""
from backend.config import GEMINI_API_KEY, GEMINI_MODEL

BRIEFING_PROMPT = """Egemen'e sesli okunacak, 2-3 cümlelik doğal bir sabah
bröfingi yaz. Türkçe, sıcak ve kısa. Aşağıdaki bilgilerden anlamlı olanları
kullan; boşsa veya alakasızsa o kısmı atla. Eğer hepsi boşsa sadece kısa
bir günaydın mesajı yaz.

Hava durumu: {weather}

Açık yapılacaklar: {todos}

Son günlerin özeti (buradan doğal bir takip sorusu çıkarabilirsin, ör.
"X nasıl gitti?"): {digests}

Sadece okunacak metni yaz, başka açıklama ekleme."""


async def _real_generate(prompt: str):
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    return await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )


async def generate_briefing_text(weather: str, todos: str, digests: str, generate_fn=None) -> str | None:
    """
    Bröfing metnini üretir. Gemini çağrısı başarısız olursa None döner
    (çağıran taraf bu durumda hiçbir şey seslendirmez, last_briefing_date'i
    de işaretlemez ki bir sonraki bağlantıda tekrar denensin).
    """
    generate = generate_fn or _real_generate
    prompt = BRIEFING_PROMPT.format(
        weather=weather or "(yok)",
        todos=todos or "(yok)",
        digests=digests or "(yok)",
    )
    try:
        response = await generate(prompt)
        text = (response.text or "").strip()
        return text or None
    except Exception as e:
        print(f"⚠️ Bröfing üretimi başarısız, atlanıyor: {e}")
        return None
```

**Testler** (`tests/test_briefing.py`, `pytest.mark.asyncio`, sahte `generate_fn` — gerçek Gemini çağrısı YOK):
- Sahte `generate_fn` ile: dönen metin aynen döndürülüyor mu, prompt'a `weather`/`todos`/`digests` içeriği gerçekten giriyor mu (prompt'u yakala, içerik kontrolü yap)
- `generate_fn` exception fırlatırsa → `None` döner, exception dışarı sızmaz
- `generate_fn` boş string dönerse → `None` döner
- Boş `weather`/`todos`/`digests` (hepsi `""`) ile çağrıldığında prompt'un çökmediğini, "(yok)" ile doldurulduğunu doğrula

`memory_digest.py` testlerindeki (`tests/test_memory_digest.py`) stili birebir örnek al.

## Task 3: Executor + Brain kablolaması

### `backend/skills/executor.py`

`__init__`'e ekle: `self.reminder_store = None   # server.py lifespan'de set edilir`

Mevcut `set_reminder` metodunu (satır ~255-274, `asyncio.sleep` + Windows `MessageBox` içeren eski implementasyon) SİL, yerine koy:

```python
    # ─── Hatırlatıcılar ──────────────────────────────────────────────────────
    async def set_reminder(self, message: str, minutes: int = None, daily_at: str = None) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        if minutes and daily_at:
            return "Hem 'minutes' hem 'daily_at' verilemez, sadece birini kullan."
        now = datetime.now()
        if daily_at:
            try:
                hour, minute = map(int, daily_at.split(":"))
            except ValueError:
                return "Saat formatı HH:MM olmalı (örn. '09:00')."
            fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if fire_at <= now:
                fire_at += timedelta(days=1)
            return self.reminder_store.add(message, fire_at, recurrence="daily")
        if not minutes:
            return "Ne zaman hatırlatacağımı belirtmelisin (dakika veya saat)."
        return self.reminder_store.add(message, now + timedelta(minutes=minutes))

    async def list_reminders(self) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        return self.reminder_store.list_active()

    async def cancel_reminder(self, query: str) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        return self.reminder_store.cancel(query)
```

Dosyanın en üstündeki `from datetime import datetime` satırını `from datetime import datetime, timedelta` yap. `subprocess`/`platform` importlarını SİLME — `open_application` gibi başka metodlar hâlâ kullanıyor.

`execute()`'daki `handlers` dict'ine ekle (mevcut `"set_reminder": self.set_reminder` zaten var, dokunma):
```python
        "list_reminders": self.list_reminders,
        "cancel_reminder": self.cancel_reminder,
```

### `backend/core/brain.py`

`_define_tools()`'daki mevcut `set_reminder` FunctionDeclaration'ı değiştir:

```python
            types.FunctionDeclaration(
                name="set_reminder",
                description=(
                    "Hatırlatıcı kurar. Tek seferlik için 'minutes', her gün "
                    "tekrarlayan rutin için 'daily_at' kullan (ikisi birden verilmez)."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Hatırlatıcı mesajı"},
                        "minutes": {"type": "integer", "description": "Kaç dakika sonra (tek seferlik)"},
                        "daily_at": {"type": "string", "description": "Her gün bu saatte, 'HH:MM' formatında (örn. '09:00')"}
                    },
                    "required": ["message"]
                }
            ),
            types.FunctionDeclaration(
                name="list_reminders",
                description="Aktif hatırlatıcıları listeler ('hatırlatıcılarım ne' gibi sorularda).",
                parameters_json_schema={"type": "object", "properties": {}, "required": []}
            ),
            types.FunctionDeclaration(
                name="cancel_reminder",
                description="Bir hatırlatıcıyı iptal eder.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "İptal edilecek hatırlatıcının metni veya bir kısmı"}},
                    "required": ["query"]
                }
            ),
```
(diğer tüm FunctionDeclaration'lara dokunma, sırasına göre `set_reminder`'ın olduğu yere ekle.)

**Testler** (`tests/test_executor_reminder_tools.py`, `tests/test_executor_memory_tools.py`'deki `FakeStore` desenini birebir örnek al — sahte `FakeReminderStore` ile `add`/`list_active`/`cancel` çağrılarını yakala):
- `set_reminder` sadece `minutes` ile → store'a doğru `fire_at` (now+minutes) ile `add` çağrılıyor mu
- `set_reminder` sadece `daily_at` ile → `recurrence="daily"` ile `add` çağrılıyor mu, geçmiş saat verilirse ertesi güne kayıyor mu
- `set_reminder` ikisi birden verilirse → hata mesajı, store'a hiç dokunulmuyor
- `set_reminder` hiçbiri verilmezse → hata mesajı
- `list_reminders`/`cancel_reminder` delege ediyor mu
- `reminder_store=None` iken üç aracın da "hazır değil" döndüğü (mevcut `test_all_five_graceful_without_store` desenine benzer)

## Task 4: Sunucu kablolaması (`backend/server.py`)

### Importlar
`from datetime import datetime, timedelta` ekle (şu an sadece `time` modülü var, `datetime` yok).

### `lifespan()`'e ekle (mevcut `memory_store` satırlarından hemen sonra, `log.info("✅ Jarvis hazır...")`'dan ÖNCE)

```python
    from backend.core.reminders import ReminderStore
    app.state.reminder_store = ReminderStore(MEMORY_DIR)
    app.state.executor.reminder_store = app.state.reminder_store

    async def _reminder_scheduler():
        """60 saniyede bir vadesi gelen hatırlatıcıları kontrol eder. Bağlı
        bir PC client varsa sesli teslim edilir; yoksa 'due' kalmaya devam
        eder ve bir sonraki taramada (client bağlanınca) teslim edilir."""
        while True:
            await asyncio.sleep(60)
            try:
                pc_clients = [cid for cid in manager.active if cid.startswith("pc-")]
                if not pc_clients:
                    continue
                for r in app.state.reminder_store.due(datetime.now()):
                    await _speak_short(pc_clients[0], f"Hatırlatma: {r['message']}")
                    app.state.reminder_store.mark_fired(r["id"])
            except Exception as e:
                log.warning(f"Hatırlatıcı zamanlayıcı hatası: {e}")

    app.state.reminder_scheduler_task = asyncio.create_task(_reminder_scheduler())
```

`yield` sonrasına (kapanış), `log.info("👋 Jarvis kapatılıyor...")`'dan ÖNCE ekle:
```python
    app.state.reminder_scheduler_task.cancel()
```

### `websocket_endpoint`'e ekle

`brain = get_brain(client_id)` satırından hemen sonra:
```python
    if client_id.startswith("pc-"):
        asyncio.create_task(_maybe_send_briefing(client_id))
```

### Yeni yardımcı fonksiyonlar (dosyanın altına, `_save_session_memory`'nin yanına)

```python
async def _maybe_send_briefing(client_id: str):
    """Günün ilk PC bağlantısında sabah bröfingini üretip seslendirir.
    Bağlantı akışını bloklamamak için websocket_endpoint'ten ayrı task
    olarak çağrılır."""
    store = app.state.reminder_store
    today = datetime.now().strftime("%Y-%m-%d")
    if store.get_last_briefing_date() == today:
        return
    from backend.core.briefing import generate_briefing_text
    executor: SkillExecutor = app.state.executor
    weather = await executor.get_weather()
    todos = app.state.memory_store.read_todos()
    digests = _recent_digests_text(app.state.memory_store)
    text = await generate_briefing_text(weather, todos, digests)
    if text is None:
        return
    store.set_last_briefing_date(today)
    await _speak_short(client_id, text)


def _recent_digests_text(store) -> str:
    """Son 2 günün digest dosyalarını birleştirir (varsa)."""
    parts = []
    for days_ago in (0, 1):
        date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        path = store.base_dir / "digests" / f"{date}.md"
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)
```

**Test yaklaşımı:** server.py'nin geri kalanı gibi (Faz 1/2'de de) pytest kapsamı yok — websocket lifecycle canlı/manuel test edilir. Task 3'ün subagent'ı sadece Task 1-3'ün testlerini çalıştırıp raporlasın; Task 4 subagent'ı tam test suite'i (`pytest -v`) çalıştırıp hiçbir şeyin bozulmadığını doğrulasın, yeni pytest EKLEMESİN.

## Task 5: Canlı test + dokümantasyon

- Egemen'le canlı test: (1) "1 dakika sonra hatırlat" kur, sunucuyu açık bırak, süre dolunca sesli geldiğini doğrula; (2) sunucuyu yeniden başlat, PC client'ı bağla, o günün ilk bröfingini duy; (3) "her gün 09:00'da X hatırlat" kur, `list_reminders` ile listelendiğini, `cancel_reminder` ile iptal edilebildiğini doğrula.
- README.md: özellikler tablosuna "Proaktiflik (sabah bröfingi, kalıcı hatırlatıcılar) ✅" ekle, yeni "Proaktiflik" bölümü (spec'e link).
- Obsidian vault (`Documents/ObsidianVault/Projeler/Jarvis/Jarvis.md`, `Yapılacaklar.md`): Faz 3 tamamlandı olarak işaretle.
- `.superpowers/sdd/progress.md`: her task tamamlandıkça satır ekle (gitignore'lu, sadece yerel takip).

## Task 6: Final whole-branch review

Fable model, tüm `proaktiflik` branch diff'i (main'e karşı). Özellikle: arka plan zamanlayıcının sunucuyu hiç düşürmediği (exception handling), `_maybe_send_briefing`'in websocket akışını bloklamadığı, `mark_fired`'ın recurrence rollover mantığının doğruluğu, ve `reminders.json`/`MEMORY.md` gibi mevcut hafıza dosyalarıyla çakışma olmadığı kontrol edilsin.
