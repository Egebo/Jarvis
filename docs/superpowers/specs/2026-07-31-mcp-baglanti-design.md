# MCP İstemci Sistemi (Faz 4) — Tasarım

**Tarih:** 2026-07-31
**Durum:** Onaylandı (Egemen, onay kuralı netleştirildi: sadece readOnlyHint:true onaysız çalışır)
**Hedef:** Jarvis'i tek tek elle kodlanan entegrasyonlardan (Calendar, Gmail, Upwork...) kurtarıp, herhangi bir MCP-uyumlu sisteme bağlanabilen genel bir asistana dönüştürmek — Claude Desktop/Claude Code'un kendi MCP host mimarisiyle aynı prensip.

## Vizyon

Egemen'in isteği: "sadece bu 3ü değil her şey diyorum, mcp bağlama sistemi kur, mcp uyumu olan her sistemi bağlayabileyim, tıpkı cowork gibi." Google Calendar, Gmail, Upwork ayrı ayrı elle kodlanan skill'ler yerine, Jarvis genel bir MCP host'u olacak; hangi server'a bağlanılacağı bir config dosyasıyla belirlenecek, yeni bir entegrasyon eklemek kod yazmak değil config'e satır eklemek olacak.

Araştırma bulguları (Egemen'e sunuldu, onaylandı):
- google-genai Python SDK'da deneysel native MCP desteği var: bir `ClientSession` doğrudan `tools` listesine verilebiliyor, SDK otomatik keşfedip otomatik çalıştırabiliyor.
- Google'ın resmi bir Calendar MCP server'ı var ama çok yeni (27 Tem 2026), OAuth akışı az belgeli. İlk somut örnek için topluluk projesi `nspady/google-calendar-mcp` (stdio, npx, iyi belgelenmiş Desktop-app OAuth) kullanılacak.
- MCP tool annotation'ları (`readOnlyHint`, `destructiveHint` vb.) var ama server'ın kendi beyanı — güvenlik sınırı olarak GÜVENİLMEZ, sadece UX sinyali. Bu yüzden onay kuralı temkinli: sadece `readOnlyHint: true` olanlar onaysız geçer.

## Mimari karar 1: Gemini'nin otomatik MCP çalıştırmasına GÜVENİLMEZ

SDK, bir `ClientSession`'ı `tools`'a verince aracı otomatik keşfedip otomatik çalıştırabiliyor ("automatic function calling"). Jarvis bunu KULLANMAYACAK — sadece keşif (`list_tools()`) için MCP kullanılacak, çalıştırma mevcut manuel `tool_executor` akışına (hafıza kaydı, hata sarmalama, onay kapısı) bağlanacak. Otomatik çalıştırma, `brain.py`'nin mevcut `memory.add_raw()` kayıtlarını ve onay mantığını by-pass eder.

## Mimari karar 2: onay kapısı TaskAgent'ta, brain.py'de DEĞİL

`brain.think()` senkron sohbet turu içinde çalışır; bir onay beklerken (`await approval_future`) sunucunun ana `receive_text()` döngüsü de aynı coroutine zincirinde bloke olur — kullanıcının söylediği "evet" cevabı hiç işlenemez, DEADLOCK. Faz 1'in TaskAgent'ı bu sorunu zaten çözmüş: `start_task` ile ayrı bir `asyncio.create_task`'a devredilir, sunucunun mesaj döngüsü serbest kalır, onay `handle_utterance` ile ayrı gelen bir mesajdan çözülür (bkz. `docs/superpowers/specs/2026-07-22-gorev-ajani-design.md`).

Bu yüzden:
- **Canlı sohbet beyni (`JarvisBrain`) sadece `readOnlyHint: true` olan MCP araçlarını doğrudan çağırabilir** (ör. "takvimimde bugün ne var" anında cevaplanır, sohbeti kesmez).
- **Yazma/silme gerektiren MCP araçları canlı sohbetin tool listesinde HİÇ YER ALMAZ** — bunlar sadece TaskAgent'a (`start_task` üzerinden) açıktır; TaskAgent'ın zaten var olan onay mekanizması (`approval_cb`, sesli evet/hayır, zaman aşımı=RED) buraya da uygulanır.
- `start_task`'ın FunctionDeclaration açıklamasına "takvim/mail gibi harici sistemlerde değişiklik gerektiren işler" eklenir ki model bu tür istekleri doğru yönlendirsin.

## Yeni bileşen: `backend/core/mcp_client.py`

- `McpToolRegistry` sınıfı: config'teki her server için `mcp` paketi (`pip install mcp`) ile bağlanır (v1: sadece stdio — `npx` gibi bir komutla başlatılan yerel süreç), `list_tools()` çağırır, her aracı `{gemini_declaration, session, real_name, read_only}` olarak kaydeder. İsim çakışmasını önlemek için Gemini'ye görünen isim `{server_id}__{tool_name}` (ör. `calendar__list-events`).
- `call(name, args) -> str`: kayıtlı session üzerinden `session.call_tool(real_name, args)`, sonucu düz metne çevirir.
- `read_only_declarations()` / `all_declarations()`: brain.py ve agent.py'nin ihtiyacına göre filtrelenmiş listeler döner.
- `is_read_only(name) -> bool`, `has(name) -> bool`: agent.py'nin onay kontrolü için.
- Bağlantı hatası (server açılmadı, OAuth token süresi dolmuş vb.): o server'ı sessizce atla, logla — bir server'ın çökmesi Jarvis'in geri kalanını düşürmesin (Faz 2/3'teki "bir alt sistem çökerse çekirdek işlev etkilenmez" prensibiyle aynı).

## Config: `Documents/Jarvis/mcp_servers.json`

Claude Desktop'ın config formatına yakın, aşina bir format:
```json
{
  "mcpServers": {
    "calendar": {
      "command": "npx",
      "args": ["-y", "@cocal/google-calendar-mcp"],
      "env": {"GOOGLE_OAUTH_CREDENTIALS": "C:\\Users\\bozca\\Documents\\Jarvis\\mcp-auth\\gcp-oauth.keys.json"}
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@github/mcp-server"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
    },
    "spotify": {
      "command": "npx",
      "args": ["-y", "@tbrgeek/spotify-mcp-server"],
      "env": {"SPOTIFY_CLIENT_ID": "...", "SPOTIFY_CLIENT_SECRET": "..."}
    }
  }
}
```
Dosya yoksa veya boşsa Jarvis MCP olmadan normal çalışmaya devam eder (yeni kurulumlarda hiçbir şey kırılmasın). Sistem generic olduğu için config'e üçten fazla/az server eklemek kodu hiç etkilemez.

**İlk rollout (Egemen'in kendi yapması gereken tek seferlik adımlar):**
| Server | Auth zorluğu | Egemen'in yapacağı |
|---|---|---|
| GitHub | Kolay | Settings → Developer settings'ten bir Personal Access Token oluşturup config'e yapıştırmak |
| Calendar | Orta | Google Cloud'da OAuth credentials oluşturup server'ı elle bir kez çalıştırıp tarayıcıdan izin vermek |
| Spotify | Orta | Spotify Developer Dashboard'da bir app oluşturup client id/secret almak, ilk çalıştırmada tarayıcı izni vermek |

Upwork bu rollout'a dahil değil — resmi API'de profil/portföy yazma mutation'ı yok (yukarıda araştırıldı), sadece okuma (iş arama, teklif takibi) mümkün olurdu; API key onayı da beklemede. Ayrı bir karar olarak ele alınacak.

## server.py / lifespan kablolaması

`lifespan()`'e diğer kaynaklar gibi eklenir: `app.state.mcp_registry = McpToolRegistry(...)`, `await app.state.mcp_registry.connect_all()` (config'te tanımlı tüm server'lara paralel bağlanır, her biri kendi try/except'i içinde). `app.state.executor.mcp_registry = app.state.mcp_registry`. Kapanışta (`yield` sonrası) tüm session'lar kapatılır.

## SkillExecutor entegrasyonu

`execute()`: mevcut statik `handlers` dict'inde bulunamayan bir `tool_name`, `self.mcp_registry` içinde aranır; oradaysa `mcp_registry.call(...)`'a delege edilir. SkillExecutor kendisi onay mantığı YAPMAZ — bu mevcut felsefeyle tutarlı (onay her zaman çağıran taraf sorumluluğunda: TaskAgent kendi kontrolünü yapar, brain.py zaten destructive MCP aracını hiç göremiyor).

## brain.py / agent.py

- `JarvisBrain`'e `self.mcp_registry` set edilir (`server.py::get_brain()` içinde, sistem promptu tazelemesiyle aynı yerde). `_define_tools()` artık statik listeye ek olarak `self.mcp_registry.read_only_declarations()` döner.
- `agent.py::TaskAgent.__init__`'e `mcp_registry` parametresi eklenir. `_declarations()` tüm MCP araçlarını (read-only + yazma) statik listeye ekler. `_exec_tool`'un "Bilinmeyen araç" fallback'i: isim `mcp_registry`'de kayıtlıysa ve `read_only == False` ise önce `await self.approval_cb(desc)` (desc: "MCP aracı '{name}' çalıştırılsın mı: {args}"), sonra `self.executor.execute(name, args)`'a devredilir; `read_only == True` ise onaysız direkt devredilir.

## Hata durumları
- Bir MCP server'a bağlanılamazsa (OAuth token süresi dolmuş, süreç başlamadı, npx kurulu değil): o server'ın araçları hiç görünmez, geri kalan sistem normal çalışır, log'a uyarı yazılır.
- MCP `call_tool` sırasında hata: `SkillExecutor.execute()`'un mevcut genel `try/except` sarmalayıcısı zaten yakalıyor (`Araç hatası (...)`), yeni kod eklemeye gerek yok.
- Config dosyası yok/bozuk: MCP hiç devrede olmadan normal başlar.

## Test planı
1. Birim: `McpToolRegistry` — sahte `ClientSession` ile tool keşfi, isim öneki, `read_only_declarations()` filtresi.
2. Birim: bağlantı hatası olan bir server'ın sessizce atlandığı, diğer server'ların etkilenmediği.
3. Birim: `SkillExecutor.execute()`'un statik handler'da olmayan bir aracı registry'ye devrettiği (sahte registry ile).
4. Birim: `TaskAgent._exec_tool`'un MCP aracı için `read_only=False` olduğunda `approval_cb`'yi çağırdığı, `read_only=True` olduğunda çağırmadığı, ve isim `mcp_registry`'de yoksa mevcut davranışın (dahili tool listesi / "Bilinmeyen araç") bozulmadığı.
5. Canlı (Egemen'le): Google Cloud'da OAuth credentials oluşturup `nspady/google-calendar-mcp`'yi elle bir kez çalıştırıp izin verme (Egemen'in yapması gereken tek manuel adım), sonra Jarvis'i başlatıp "takvimimde bugün ne var" gibi salt-okunur bir soru + "yarın 15:00'e diş hekimi ekle" gibi TaskAgent üzerinden geçen bir yazma testi.

## Kapsam dışı (bilinçli)
- **Gmail/Upwork bu fazda kodlanmıyor** — sistem generic olduğu için sadece config'e yeni bir server eklemek yeterli olacak, ayrı kod gerekmeyecek. Gmail community server'ı veya Upwork API onayı geldiğinde (kendi MCP server'ı yazılabilir ya da hazır bir tane bulunabilir) config'e eklenir.
- **Uzak/HTTP tabanlı MCP server'lar (Google'ın resmi Calendar MCP'si gibi) desteklenmiyor v1'de** — sadece stdio (yerel süreç) server'lar. Resmi server'lar olgunlaşınca/belgelenince eklenir.
- **Jarvis'in kendi kod tabanında OAuth akışı yok** — v1'de kullanıcı OAuth'u MCP server'ın kendi CLI'ıyla elle bir kez tamamlıyor (token dosyaya kaydediliyor), Jarvis sadece hazır token'ı kullanan server sürecini başlatıyor.
- **MCP prompts/resources desteklenmiyor** — sadece tools (SDK'nın kendisi de deneysel desteği tools-only olarak tanımlıyor).
- **Çoklu kullanıcı/yetki seviyesi yok** — tek profil, Faz 2/3'teki kapsam dışı kararlarıyla aynı.
