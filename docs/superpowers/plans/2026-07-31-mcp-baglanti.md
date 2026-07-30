# MCP İstemci Sistemi (Faz 4) — Uygulama Planı

Spec: `docs/superpowers/specs/2026-07-31-mcp-baglanti-design.md`
Branch: `mcp-baglanti` (main'den)
Süreç: subagent-driven — her task için taze implementer + task reviewer, sonra final whole-branch review (fable).

Doğrulanmış gerçek `mcp` paketi (PyPI: `mcp`) API'si (stdio istemci):
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="npx", args=[...], env={...})
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()   # result.tools: her biri .name, .description, .inputSchema, .annotations
        call_result = await session.call_tool("tool-adı", arguments={...})  # call_result.content: TextContent listesi
```
Uzun ömürlü (sunucu ömrü boyunca açık) tutmak için `contextlib.AsyncExitStack` ile context manager'lar manuel açılır (`enter_async_context`), tek seferde `aclose()` ile kapatılır.

## Task 1: `backend/core/mcp_client.py` — McpToolRegistry

```python
"""
Jarvis'i genel bir MCP host'una çevirir: config'te tanımlı MCP server'lara
bağlanır, araçlarını keşfeder, Gemini function-calling şemasına çevirir.
Çalıştırma mevcut manuel tool_executor akışına (SkillExecutor) bağlanır -
SDK'nın otomatik MCP çalıştırmasına GÜVENİLMEZ (hafıza kaydı + onay kapısı
bypass olur).
Spec: docs/superpowers/specs/2026-07-31-mcp-baglanti-design.md
"""
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path

log = logging.getLogger("jarvis")


class McpToolRegistry:
    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._tools: dict[str, dict] = {}

    async def connect_all(self, config_path: Path, connect_fn=None):
        """config_path yoksa/bozuksa sessizce boş kalır - MCP olmadan Jarvis
        normal çalışmaya devam eder. Her server kendi try/except'i içinde;
        biri başarısız olursa diğerleri etkilenmez."""
        connect = connect_fn or self._real_connect
        if not config_path.exists():
            return
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"MCP config okunamadı: {e}")
            return

        for server_id, server_cfg in config.get("mcpServers", {}).items():
            try:
                session = await connect(server_id, server_cfg, self._exit_stack)
                await self._register_tools(server_id, session)
                log.info(f"🔌 MCP server bağlandı: {server_id}")
            except Exception as e:
                log.warning(f"MCP server '{server_id}' bağlanamadı: {e}")

    async def _real_connect(self, server_id: str, server_cfg: dict, exit_stack: AsyncExitStack):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )
        read, write = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _register_tools(self, server_id: str, session):
        from google.genai import types

        result = await session.list_tools()
        for tool in result.tools:
            exposed_name = f"{server_id}__{tool.name}"
            read_only = bool(getattr(tool.annotations, "readOnlyHint", False)) if tool.annotations else False
            self._tools[exposed_name] = {
                "session": session,
                "real_name": tool.name,
                "read_only": read_only,
                "declaration": types.FunctionDeclaration(
                    name=exposed_name,
                    description=tool.description or f"{server_id}: {tool.name}",
                    parameters_json_schema=tool.inputSchema or {"type": "object", "properties": {}},
                ),
            }

    def has(self, name: str) -> bool:
        return name in self._tools

    def is_read_only(self, name: str) -> bool:
        entry = self._tools.get(name)
        return bool(entry and entry["read_only"])

    def read_only_declarations(self) -> list:
        return [t["declaration"] for t in self._tools.values() if t["read_only"]]

    def all_declarations(self) -> list:
        return [t["declaration"] for t in self._tools.values()]

    async def call(self, name: str, args: dict) -> str:
        entry = self._tools.get(name)
        if entry is None:
            return f"Bilinmeyen MCP aracı: {name}"
        result = await entry["session"].call_tool(entry["real_name"], arguments=args)
        texts = [getattr(block, "text", None) for block in (result.content or [])]
        texts = [t for t in texts if t]
        return "\n".join(texts) if texts else "(boş sonuç)"

    async def close(self):
        await self._exit_stack.aclose()
```

**Testler** (`tests/test_mcp_client.py`, `pytest.mark.asyncio`, `tmp_path` ile config dosyası — GERÇEK npx/subprocess ASLA çalıştırılmaz, `connect_fn` her zaman sahte):
- `connect_all` config dosyası yoksa hiçbir şey yapmadan döner (`_tools` boş kalır)
- Bozuk JSON config → sessizce boş kalır, exception dışarı sızmaz
- Sahte `connect_fn` ile: iki server'lı bir config, her server'ın araçları `{server_id}__{tool_name}` öneki ile kayıtlı oluyor mu (sahte `session.list_tools()` sahte `Tool` nesneleri döndürür - basit bir `SimpleNamespace(name=..., description=..., inputSchema=..., annotations=SimpleNamespace(readOnlyHint=True/False) veya None)` kullanılabilir)
- `read_only_declarations()` sadece `readOnlyHint=True` olanları döndürüyor, `all_declarations()` hepsini döndürüyor
- Bir server'ın `connect_fn`'i exception fırlatırsa (sahte bağlantı hatası): o server'ın araçları hiç kaydedilmez, DİĞER server'ın araçları etkilenmez (aynı `connect_all` çağrısında iki server, biri patlıyor)
- `has()`/`is_read_only()` bilinmeyen isimde `False` döner (crash yok)
- `call()`: sahte session'ın `call_tool()`'u sahte bir `SimpleNamespace(content=[SimpleNamespace(text="sonuç")])` döndürünce metni doğru çıkarıyor mu; bilinmeyen isimde "Bilinmeyen MCP aracı" döner
- `call()`: `content` boşsa "(boş sonuç)" döner, crash yok

## Task 2: SkillExecutor entegrasyonu

`backend/skills/executor.py`:
- `__init__`'e ekle: `self.mcp_registry = None   # server.py lifespan'de set edilir` (diğer `= None` satırlarının yanına)
- `execute()`'u değiştir - statik handler bulunamazsa MCP registry'ye düş:
```python
    async def execute(self, tool_name: str, tool_input: Dict) -> str:
        handlers = {
            # ... (mevcut sözlük AYNEN kalır, dokunma)
        }

        handler = handlers.get(tool_name)
        if handler:
            try:
                return await handler(**tool_input)
            except Exception as e:
                return f"Araç hatası ({tool_name}): {str(e)}"

        if self.mcp_registry and self.mcp_registry.has(tool_name):
            try:
                return await self.mcp_registry.call(tool_name, tool_input)
            except Exception as e:
                return f"Araç hatası ({tool_name}): {str(e)}"

        return f"Bilinmeyen araç: {tool_name}"
```
- `start_task()`'taki `runner_factory` içindeki `TaskAgent(...)` çağrısına `mcp_registry=self.mcp_registry` ekle:
```python
        def runner_factory(tm):
            agent = TaskAgent(description, FileTools(WORKSPACE_DIR), executor=self,
                              approval_cb=tm.request_approval, mcp_registry=self.mcp_registry)
            return agent.run()
```

**Testler** (`tests/test_executor_mcp.py`, mevcut `tests/test_executor_memory_tools.py`'deki `FakeStore` desenini örnek al - sahte `FakeMcpRegistry` ile `has`/`call` çağrılarını yakala):
- Bilinmeyen bir `tool_name`, `mcp_registry.has()` `True` dönerse `mcp_registry.call()`'a delege ediliyor mu
- `mcp_registry.has()` `False` dönerse (veya `mcp_registry is None`) hâlâ "Bilinmeyen araç" dönüyor mu
- Statik bir handler (ör. `get_weather`) varken, aynı isimde bir MCP aracı da "varmış" gibi sahte registry kuruluşa rağmen ÖNCE statik handler çalışıyor mu (statik isimler MCP'den önceliklidir - registry hiç sorulmaz)
- MCP `call()` exception fırlatırsa "Araç hatası" formatında yakalanıyor

## Task 3: brain.py entegrasyonu

`backend/core/brain.py`:
```python
class JarvisBrain:
    def __init__(self, mcp_registry=None):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.memory = ConversationMemory(max_turns=20)
        self.mcp_registry = mcp_registry
        self.tools = self._define_tools()
        self.system_prompt = self._build_system_prompt()
```
`_define_tools()`'un SONUNU değiştir (mevcut `declarations = [...]` listesinin tamamı AYNEN kalır, sadece `return` öncesine ekleme yapılır):
```python
        ]
        if self.mcp_registry:
            declarations += self.mcp_registry.read_only_declarations()
        return [types.Tool(function_declarations=declarations)]
```
(`declarations` zaten bir Python listesi olduğu için `+=` ile MCP'nin döndürdüğü `FunctionDeclaration` listesini ekler.)

**Testler** (`tests/test_brain_mcp.py` - mevcut `tests/test_brain_memory.py`'deki monkeypatch desenini örnek al):
- Sahte bir `mcp_registry` (basit obje, `read_only_declarations()` iki sahte `FunctionDeclaration` döndürür) ile `JarvisBrain(mcp_registry=fake)` oluşturulunca, `brain.tools[0].function_declarations` içinde hem mevcut sabit araçlar hem de o iki MCP aracının olduğunu doğrula
- `mcp_registry=None` (varsayılan, mevcut davranış) ile oluşturulunca tool sayısı DEĞİŞMEMİŞ olmalı (regresyon testi - mevcut `test_brain_memory.py` testlerinin hâlâ geçtiğini de doğrula)

## Task 4: agent.py (TaskAgent) entegrasyonu

`backend/core/agent.py`:
```python
class TaskAgent:
    def __init__(self, description, file_tools: FileTools, executor,
                 approval_cb, mcp_registry=None, generate_fn=None, max_steps: int = AGENT_MAX_STEPS):
        self.description = description
        self.ft = file_tools
        self.executor = executor
        self.approval_cb = approval_cb
        self.mcp_registry = mcp_registry
        self.max_steps = max_steps
        self._generate = generate_fn or self._real_generate
        self._contents = []
```
`_declarations()`'ın başındaki `@staticmethod` dekoratörünü SİL (artık instance method - `self.mcp_registry`'e erişmesi gerekiyor). İmzayı `def _declarations(self):` yap. Mevcut 8 `FunctionDeclaration`'ı İÇEREN `return [...]` satırını değiştir:
```python
    def _declarations(self):
        from google.genai import types
        schema = lambda props, req: {"type": "object", "properties": props, "required": req}
        s = {"type": "string"}
        declarations = [
            # ... (mevcut 8 FunctionDeclaration AYNEN kalır, sadece isim `declarations` oldu)
        ]
        if self.mcp_registry:
            declarations += self.mcp_registry.all_declarations()
        return declarations
```
(Çağrı yeri `_real_generate` içindeki `tools=[types.Tool(function_declarations=self._declarations())]` DEĞİŞMEZ - `self._declarations()` şeklinde çağrılıyordu zaten, staticmethod'dan instance method'a geçiş çağrı sözdizimini etkilemez.)

`_exec_tool`'un SONUNU değiştir (mevcut `if name == "web_search": ...` satırından SONRA, `return f"Bilinmeyen araç: {name}"`'DAN ÖNCE ekle):
```python
            if name == "web_search":
                return await self.executor.web_search(args["query"])
            if self.mcp_registry and self.mcp_registry.has(name):
                if not self.mcp_registry.is_read_only(name):
                    approved = await self.approval_cb(f"MCP aracı '{name}' çalıştırılsın mı: {args}")
                    if not approved:
                        return "Kullanıcı bu adımı REDDETTİ. Adımı atla, işi elindekiyle sürdür."
                return await self.mcp_registry.call(name, args)
            return f"Bilinmeyen araç: {name}"
```
(`requires_approval(name, args, self.ft.workspace)` fonksiyonu bilinmeyen isimlerde güvenle `(False, "")` döner - MCP isimleri için hiç tetiklenmez, bu yüzden MCP'nin KENDİ onay kontrolü ayrıca yapılıyor, çift onay riski yok.)

**Testler** (`tests/test_agent_mcp.py` veya mevcut `tests/test_agent.py`'ye ekleme - önce o dosyayı okuyup mevcut sahte `generate_fn`/`approval_cb` desenini birebir örnek al):
- Sahte `mcp_registry` (`has()` True, `is_read_only()` False) + ajan bir MCP aracını çağırdığında `approval_cb` çağrılıyor mu; `approval_cb` `False` dönerse "REDDETTİ" mesajı dönüyor ve `mcp_registry.call()` HİÇ çağrılmıyor mu
- Sahte `mcp_registry` (`is_read_only()` True) ile: `approval_cb` HİÇ çağrılmadan direkt `mcp_registry.call()` çağrılıyor mu
- `mcp_registry=None` (varsayılan) ile mevcut testlerin (dosya işlemleri, web_search) hâlâ eskisi gibi çalıştığını doğrula (regresyon)
- `_declarations()` artık instance method - `mcp_registry` sahte iki araç döndürünce dönen listede o ikisinin de olduğunu doğrula

## Task 5: server.py + config.py kablolaması

`backend/config.py`'ye ekle (Kalıcı Hafıza bölümünün altına):
```python
# ─── MCP (Model Context Protocol) ────────────────────────────────────────────
MCP_CONFIG_PATH = Path(os.getenv("JARVIS_MCP_CONFIG", str(JARVIS_DATA_DIR / "mcp_servers.json")))
```

`backend/requirements.txt`'e ekle: `mcp>=1.0.0`

`backend/server.py`:
- Import satırına `MCP_CONFIG_PATH` ekle: `from backend.config import SERVER_HOST, SERVER_PORT, FOLLOWUP_WINDOW, MEMORY_DIR, MCP_CONFIG_PATH`
- `lifespan()`'e, `reminder_store` kablolamasından SONRA, zamanlayıcı task'ından ÖNCE VEYA SONRA (sıra önemli değil) ekle:
```python
    from backend.core.mcp_client import McpToolRegistry
    app.state.mcp_registry = McpToolRegistry()
    await app.state.mcp_registry.connect_all(MCP_CONFIG_PATH)
    app.state.executor.mcp_registry = app.state.mcp_registry
```
- `yield`'den SONRA, mevcut `reminder_scheduler_task.cancel()`'dan sonra ekle:
```python
    await app.state.mcp_registry.close()
```
- `get_brain()`'i değiştir:
```python
def get_brain(client_id: str) -> JarvisBrain:
    if client_id not in sessions:
        sessions[client_id] = JarvisBrain(mcp_registry=app.state.mcp_registry)
    else:
        sessions[client_id].system_prompt = sessions[client_id]._build_system_prompt()
    return sessions[client_id]
```

Ayrıca bir örnek config dosyası ekle: repo köküne `mcp_servers.example.json` (gerçek config `Documents/Jarvis/` altında, repo DIŞINDA kalır - Faz 2/3'teki veri-repo-dışında prensibiyle aynı):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@github/mcp-server"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."}
    },
    "calendar": {
      "command": "npx",
      "args": ["-y", "@cocal/google-calendar-mcp"],
      "env": {"GOOGLE_OAUTH_CREDENTIALS": "C:\\Users\\KULLANICI\\Documents\\Jarvis\\mcp-auth\\gcp-oauth.keys.json"}
    },
    "spotify": {
      "command": "npx",
      "args": ["-y", "@tbrgeek/spotify-mcp-server"],
      "env": {"SPOTIFY_CLIENT_ID": "...", "SPOTIFY_CLIENT_SECRET": "..."}
    }
  }
}
```

**Test yaklaşımı:** server.py'nin geri kalanı gibi bu task da pytest kapsamı EKLEMEZ (websocket lifecycle canlı test edilir, Faz 2/3'teki aynı karar). Bu task'ın subagent'ı Task 1-4'ün testlerini + tam suite'i (`pytest -v` / `pytest -q`) çalıştırıp raporlasın, `python -c "from backend.server import app; print('OK')"` ile modülün temiz import edildiğini doğrulasın (mcp paketi kurulu olmalı - `pip install mcp` gerekebilir, requirements.txt'e eklendiği için `pip install -r backend/requirements.txt` ile kurulu olduğunu varsay, kurulu değilse kurmayı dene).

## Task 6: Canlı test + dokümantasyon

- Egemen'in yapması gereken tek seferlik adımlar (spec'teki tablo): GitHub PAT oluşturma (en kolay, önce bununla başla), Calendar OAuth, Spotify Developer app - her biri `mcp_servers.json`'a (Documents/Jarvis altında, Egemen'in kendi makinesinde) elle eklenir.
- Canlı test: GitHub bağlıyken "reposuna en son commit ne" gibi salt-okunur bir soru sohbette anında cevaplanıyor mu; Calendar bağlıyken "yarın 15:00'e X ekle" `start_task` üzerinden onay isteyip ekliyor mu.
- README.md: "MCP İstemci Sistemi" bölümü eklensin, spec'e link, örnek config dosyasına referans.
- Obsidian vault + `.superpowers/sdd/progress.md` güncellensin.

## Task 7: Final whole-branch review

Fable model. Özellikle: `AsyncExitStack`'in gerçekten tüm session'ları sunucu ömrü boyunca canlı tuttuğu (erken kapanma riski var mı), `_exec_tool`'daki çift-onay riski olmadığı (requires_approval + MCP'nin kendi kontrolü çakışmıyor), brain.py'nin SADECE read-only MCP araçlarını gördüğü (bir yazma aracının yanlışlıkla canlı sohbete sızmadığı), ve bir MCP server'ın bağlantı hatasının sunucuyu hiç etkilemediği (lifespan'de `connect_all` içindeki try/except'lerin gerçekten her server'ı izole ettiği) doğrulansın.
