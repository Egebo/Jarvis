# Kalıcı Hafıza (Faz 2) — Tasarım

**Tarih:** 2026-07-22
**Durum:** Onaylandı (Egemen, sesli/metin tasarım oturumu)
**Hedef:** Jarvis'i oturumdan oturuma hiçbir şey hatırlamayan bir asistandan, Egemen'i tanıyan ve geçmişi hatırlayan gerçek bir kişisel danışmana taşımak. Faz 1'in (Görev Ajanı) üzerine kurulur; Faz 3'ün (proaktiflik) önkoşuludur.

## Vizyon

Egemen'in isteği: "bildiğin benim hafızam olsun istiyorum, danışmanım asistanım". Üç şeyi kapsıyor: (1) açıkça söylediklerini hatırlama ("not al"), (2) konuşmalardan kendiliğinden öğrenme, (3) geçmiş konuşmaları hatırlayabilme ("dün ne konuşmuştuk"). Yakalama yöntemi hibrit: hem açık komut hem otomatik çıkarım.

## Mimari: kategorilere ayrılmış dosya deposu + iki katmanlı okuma

Kendi hafıza sistemimin (bu konuşmanın kendisinde kullandığım) sadeleştirilmiş hali: konuya göre bölünmüş Markdown dosyaları, kısa bir index her zaman yüklü, büyümeye açık kısımlar aranarak getiriliyor.

### Depo: `backend/memory/`

**Her oturum başında TAM içeriğiyle yüklenen** (küçük/sınırlı kalması beklenir, anlık gecikmesiz erişim gerekir):
- `karakter-tercihler.md` — Jarvis'in Egemen'e nasıl davranması gerektiği (ton, düzeltmeler)
- `hakkimda.md` — kalıcı gerçekler: iş, hayat durumu, rutinler, önemli insanlar
- `ilgi-alanlarim.md` — zevkler, hobiler, beğeniler

**Sadece araç çağrısıyla aranan** (sınırsız büyümeye açık):
- `digests/YYYY-MM-DD.md` — geçmiş oturum özetleri (bir günde birden fazla oturum olursa aynı dosyaya saat başlıklı olarak eklenir)
- `todos.md` — yapılacaklar listesi (checkbox)

**`MEMORY.md`** — tüm dosyaların bir satırlık özeti/indeksi; her zaman yüklenir.

Yeni bir konu ortaya çıkarsa (üç başlangıç kategorisine girmeyen, tekrar eden bir tema) hem açık `remember()` hem otomatik özetleme yolu **aynı fonksiyonu** (`MemoryStore.save_fact`) kullanarak yeni bir dosya oluşturabilir ve `MEMORY.md`'ye ekleyebilir — tek kod yolu, iki tetikleyici.

### Yeni bileşen: `backend/core/long_term_memory.py`

- `MemoryStore` sınıfı: `save_fact(category, text)`, `append_digest(date, text)`, `read_core_files() -> str` (üç ana dosya + index, birleştirilmiş), `add_todo(item)`, `complete_todo(item)`, `read_todos()`, `search_digests(query) -> str` (basit anahtar kelime araması, embedding yok).
- `summarize_and_save(conversation_turns)` async fonksiyonu: arka plan özetleme çağrısını yapar (aşağıda).

### Sohbet beynine eklenen 5 araç (`backend/skills/executor.py` + `backend/core/brain.py`)

| Araç | Ne zaman |
|---|---|
| `remember(fact, category)` | "not al", "unutma ki" |
| `add_todo(item)` | "yapılacaklara ekle" |
| `complete_todo(item)` | "şunu tamamladım" |
| `list_todos()` | "listemde ne var" |
| `recall(query)` | "geçen hafta ne konuşmuştuk", "dün X hakkında ne demiştim" |

`category` alanı serbest metin; `MemoryStore.save_fact` dosya yoksa oluşturur.

### JarvisBrain entegrasyonu

`JarvisBrain.__init__` içinde, oturum başına **bir kez**, `MemoryStore.read_core_files()` çıktısı `SYSTEM_PROMPT`'a eklenir. Aynı oturum içinde `remember()` çağrısı zaten o anki konuşmanın (function response) parçası olduğu için yeniden okumaya gerek yok.

### Otomatik yakalama (arka plan)

**Tetikleyici:** Mevcut iki olay yeniden kullanılır — yeni zamanlayıcı eklenmez:
1. WebSocket bağlantısı koptuğunda (`WebSocketDisconnect`)
2. Kullanıcı `reset` komutu gönderdiğinde

**Akış:**
```
Oturum biter (kopma/reset)
  → session'ın ConversationMemory turları alınır
  → çok kısaysa (ör. tek bir "merhaba") hiçbir şey yapılmaz
  → summarize_and_save(): gemini-3.1-flash-lite'a TEK çağrı, function-calling ile
    extract_memory(digest: str|null, facts: [{category, text}]) döndürür
  → digest varsa digests/YYYY-MM-DD.md'ye eklenir
  → her fact için MemoryStore.save_fact(category, text)
```

**Çıkarım prompt'u cömert olmalı:** Şüpheli durumda "kaydet" tarafına eğilsin — Egemen açıkça "gerçekten iyi bir otomatik hafıza" istedi; aşırı temkinli bir prompt değerli bilgiyi kaçırır. Bu iş kullanıcı zaten ayrılmış/sıfırlamışken çalıştığı için sohbet gecikmesine hiç dokunmaz.

## Hata durumları

- Dosya I/O hatası (disk, izin): logla, sohbeti düşürme — hafıza bir katkı, çekirdek işlev değil.
- Arka plan özetleme çağrısı 429/503: bir kez tekrar dene, yine olmazsa o oturumun özeti sessizce kaybolur.
- `summarize_and_save` istisna fırlatırsa: `asyncio.create_task` içinde yakalanır, loglanır, sunucuyu etkilemez.

## Test planı

1. **Birim:** `MemoryStore` dosya okuma/yazma/kategori oluşturma (Faz 1'in `FileTools` testleriyle aynı desen, `tmp_path`).
2. **Birim:** `search_digests()` arama mantığı, örnek digest dosyalarıyla.
3. **Entegrasyon:** Yeni 5 aracın `SkillExecutor`'a bağlanması (websocket text testi, Faz 1'deki `test_executor_task_tools.py` deseni).
4. **Entegrasyon:** `summarize_and_save` sahte `generate_fn` ile (gerçek Gemini'ye çıkmadan) — kısa konuşma → boş sonuç, önemli konuşma → digest+fact yazıldığı doğrulanır.
5. **Canlı (Egemen'le):** "Not al: ..." de → bağlantıyı kes/sıfırla → yeniden bağlan → hatırladığını doğrula. Birkaç mesajlık anlamlı bir sohbet sonrası bağlantıyı kes → `digests/` klasöründe özet dosyası oluştuğunu kontrol et.

## Kapsam dışı (bilinçli)

- **Konuşmacı ayrımı yok** — tüm hafıza tek profil. Ses kimliği doğrulama (bkz. `jarvis-ses-kimlik` hafıza notu) geldiğinde kişiye özel ayrım eklenir.
- **Vektör arama/embedding yok** — `recall()`/`search_digests()` basit anahtar kelime araması yapar. Sonuçlar yetersiz kalırsa ileride yükseltilir.
- **Otomatik dosya budama/sıkıştırma yok** — `digests/` uzun vadede büyüyecek, şimdilik sorun değil.
- **İnaktivite zaman aşımı tetikleyicisi yok** — sadece disconnect/reset. Sohbetler hiç kopmadan günlerce açık kalırsa özet hiç yazılmaz; ileride gerekirse eklenir.
- **Cloud/uzak barındırma tartışması bu spec'in dışında** — hafıza tasarımı sunucunun nerede çalıştığından bağımsız (dosya tabanlı), ayrı bir gündemde ele alınacak.
