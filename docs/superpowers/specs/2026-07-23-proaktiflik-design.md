# Proaktiflik (Faz 3) — Tasarım

**Tarih:** 2026-07-23
**Durum:** Onaylandı (Egemen, iki tetikleme kararı AskUserQuestion ile netleştirildi)
**Hedef:** Jarvis'i sadece soruya cevap veren bir asistandan, kendiliğinden inisiyatif alan gerçek bir danışmana taşımak: sabah bröfingi, geçmişten takip konuları, gerçekten kalıcı (sunucu kapansa da hayatta kalan) hatırlatıcılar. Faz 1 (Görev Ajanı) ve Faz 2'nin (Kalıcı Hafıza) üzerine kurulur — bröfing içeriği Faz 2'nin hafızasından (todos, digests) beslenir.

## Vizyon

Egemen'in kullanım şekli: sunucuyu manuel başlatıyor, 7/24 açık değil. Bu yüzden proaktiflik "sabit saatte cron" değil, **PC client bağlandığında** tetiklenir — günün ilk bağlantısı doğal olarak "günaydın" anıdır. Aynı sebeple takip konuları da ayrı bir sohbet-arası kesinti değil, sabah bröfinginin bir parçası.

İki karar (Egemen onayladı):
1. Bröfing + vadesi gelmiş hatırlatıcılar → PC client'ın günün ilk bağlantısında kontrol edilir.
2. Takip konuları → sadece sabah bröfingine gömülü, ayrı bir tetikleyicisi yok.

## Kapsam

### 1. Kalıcı hatırlatıcılar — yeni `backend/core/reminders.py`

Mevcut `set_reminder` (executor.py) in-memory `asyncio.sleep` + Windows `MessageBox` kullanıyor: sunucu kapanınca kaybolur, sesli asistanda popup pencere göstermek zaten yanlış kanal. Faz 3'te tamamen değişir:

**`ReminderStore`** (`MemoryStore` ile aynı desen — JSON dosya, `MEMORY_DIR/reminders.json`):
```json
{
  "reminders": [
    {"id": "uuid", "message": "...", "fire_at": "2026-07-24T09:00:00", "recurrence": null, "done": false}
  ],
  "last_briefing_date": "2026-07-23"
}
```
- `recurrence`: `null` (tek seferlik) veya `"daily"` (her gün aynı saatte).
- Metodlar: `add(message, fire_at, recurrence=None)`, `due(now) -> list[reminder]` (fire_at geçmiş VE done=False olanlar), `mark_fired(id)` (tek seferlikte done=True, recurrence="daily" ise fire_at'i +1 gün ileri alır), `list_active() -> str`, `cancel(query) -> bool` (fuzzy metin eşleşmesi, `complete_todo` ile aynı desen), `get_last_briefing_date()` / `set_last_briefing_date(date)`.

**Yeni/değişen araçlar** (`executor.py` + `brain.py::_define_tools`):
| Araç | Parametreler | Ne zaman |
|---|---|---|
| `set_reminder` | `message`, `minutes` (opsiyonel, tek seferlik) VEYA `daily_at` ("HH:MM", tekrarlayan) | "10 dakika sonra hatırlat", "her sabah 8'de hatırlat" |
| `list_reminders` | — | "hatırlatıcılarım ne" |
| `cancel_reminder` | `query` | "şu hatırlatıcıyı iptal et" |

`minutes` ve `daily_at` karşılıklı dışlar; ikisi de boşsa hata mesajı döner (LLM'e).

**Teslimat (arka plan zamanlayıcı):** `lifespan()`'e yeni bir arka plan görevi eklenir — `asyncio.create_task`, 60 saniyede bir `ReminderStore.due(now)` kontrol eder. Vadesi gelmiş bir hatırlatıcı varsa VE en az bir `pc-*` client bağlıysa (mevcut "onaylar sadece pc-* client" kararıyla tutarlı, 22 Tem), `task_event`'teki gibi TTS ile seslendirilip `manager.broadcast` edilir, sonra `mark_fired`. Bağlı PC client yoksa hatırlatıcı `due` kalmaya devam eder — bir sonraki bağlantıda (veya sonraki 60sn taramasında client bağlanınca) "gecikmeli" teslim edilir, kaybolmaz.

### 2. Sabah bröfingi — yeni `backend/core/briefing.py`

**Tetikleyici:** `websocket_endpoint`'te `client_id.startswith("pc-")` bağlantısı kabul edildiğinde, `ReminderStore.get_last_briefing_date() != bugün` ise `asyncio.create_task(_maybe_brief(...))` — bağlantıyı bloklamadan çalışır.

**İçerik toplama:**
- `executor.get_weather()` (mevcut araç, doğrudan çağrılır)
- `MemoryStore.read_todos()` (açık maddeler)
- Son 2 günün digest dosyaları (`MemoryStore.search_digests` değil — doğrudan `digests/YYYY-MM-DD.md` son 2 gün, varsa) → "takip konusu" kaynağı

**Üretim:** `generate_briefing_text(weather, todos, recent_digests, generate_fn=None) -> str | None` — `memory_digest.py`'deki `generate_fn` dependency-injection deseniyle test edilebilir (gerçek Gemini çağrısı yerine testte sahte fonksiyon). Tek Gemini çağrısı, function-calling YOK — düz metin üretimi: "Egemen'e sesli okunacak, 2-3 cümlelik, doğal bir sabah bröfingi yaz. Hava durumu, açık yapılacaklardan en fazla 1-2 tanesi, ve varsa geçmiş digestten doğal bir takip sorusu ('X nasıl gitti?' gibi) içersin. Hiçbiri anlamlı değilse kısa bir günaydın yeterli." Boş/anlamsız girdi (hava yok, todo yok, digest yok) → sadece kısa bir günaydın metni.

**Teslimat:** Üretilen metin `mark_fired` mantığına benzer şekilde `set_last_briefing_date(bugün)` ile işaretlenir (aynı gün tekrar tetiklenmesin — sunucu aynı gün içinde restart edilirse bile tekrarlamaz), sonra TTS ile seslendirilip broadcast edilir (aynı `task_event` deseni).

## Hata durumları

- `reminders.json` bozuksa/okunamıyorsa: logla, boş depoyla devam et (Faz 2'nin "hafıza bir katkı, çekirdek işlev değil" prensibiyle tutarlı).
- Arka plan zamanlayıcı döngüsünde istisna: `try/except` her turda, logla, döngü devam etsin — sunucuyu düşürmesin.
- Bröfing üretimi (Gemini çağrısı) başarısız olursa: sessizce atlanır, `last_briefing_date` işaretlenmez (yeniden bağlanınca tekrar denenir) — `memory_digest.py`'nin retry mantığından farklı olarak burada retry YOK, çünkü briefing zaten "bir sonraki bağlantıda tekrar denenebilir" bir şey.

## Test planı

1. **Birim:** `ReminderStore` CRUD + `due()` hesaplama (tmp_path, açık `now` parametresi verilerek — gerçek saat beklenmez).
2. **Birim:** `recurrence="daily"` rollover — `mark_fired` sonrası `fire_at` +1 gün ileri alınıyor mu.
3. **Birim:** `generate_briefing_text` sahte `generate_fn` ile — boş girdi → kısa günaydın, dolu girdi → hava/todo/takip içeren metin.
4. **Entegrasyon:** `set_reminder`/`list_reminders`/`cancel_reminder` araçlarının `SkillExecutor`'a bağlanması (Faz 2'deki `test_executor_memory_tools.py` deseni).
5. **Canlı (Egemen'le):** "1 dakika sonra hatırlat" kur, sunucuyu açık bırak → süre dolunca sesli geldiğini doğrula. Sunucuyu yeniden başlat, PC client'ı bağla → o günün ilk bröfingini duy.

## Kapsam dışı (bilinçli)

- **Haftalık/aylık karmaşık tekrar (cron ifadesi) yok** — sadece `daily`. İhtiyaç çıkarsa genişletilir.
- **Takvim entegrasyonu yok** (Google Calendar vb.) — ayrı gündem.
- **Web/mobil client'a proaktif teslimat yok** — sadece `pc-*` client hedefleniyor (mevcut onay-sadece-PC kararıyla tutarlı); web arayüzü şu an sürekli açık bir arayüz değil.
- **Zaman dilimi yönetimi yok** — yerel sistem saati kullanılır.
- **Konuşmacı ayrımı yok** — Faz 2'deki kapsam-dışı kararı burada da geçerli.
