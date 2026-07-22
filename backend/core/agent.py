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
        # Sohbet geçmişi düz dict/list olarak tutulur (test edilen sahte Part/FunctionCall
        # nesneleri gerçek google-genai pydantic tiplerinden değil; types.Content(...) bunları
        # kabul etmeyebilir). SDK tiplerine dönüşüm sadece _real_generate içinde yapılır.
        self._contents = []

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
        sdk_contents = [self._to_sdk_content(c) for c in contents]
        return await self._client.aio.models.generate_content(
            model=AGENT_MODEL, contents=sdk_contents, config=config)

    @staticmethod
    def _to_sdk_content(entry):
        """Düz dict geçmiş girdisini gerçek google.genai types.Content'e çevirir."""
        from google.genai import types
        if not isinstance(entry, dict):
            return entry  # zaten SDK tipi ise dokunma
        sdk_parts = []
        for part in entry.get("parts", []):
            if isinstance(part, dict):
                if "function_response" in part:
                    fr = part["function_response"]
                    sdk_parts.append(types.Part.from_function_response(
                        name=fr["name"], response=fr["response"]))
                elif "function_call" in part:
                    fc = part["function_call"]
                    sdk_parts.append(types.Part(function_call=types.FunctionCall(
                        name=fc["name"], args=fc.get("args") or {})))
                else:
                    sdk_parts.append(types.Part(text=part.get("text", "")))
            else:
                sdk_parts.append(part)  # zaten SDK Part'ı
        return types.Content(role=entry.get("role", "user"), parts=sdk_parts)

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
        contents = [{"role": "user", "parts": [{"text": f"Görev: {self.description}"}]}]

        for step in range(self.max_steps + 1):
            if step == self.max_steps:
                contents.append({"role": "user", "parts": [{
                    "text": "Adım limitine ulaştın. Yeni araç çağırma; elindekiyle kısa sesli özetini ver."}]})
            response = await self._generate_with_retry(contents)
            parts = response.candidates[0].content.parts or []
            fcs = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not fcs or step == self.max_steps:
                return (getattr(response, "text", "") or "Görev tamamlandı.").strip()

            contents.append({"role": "model", "parts": list(parts)})
            results = []
            for fc in fcs:
                args = dict(fc.args) if fc.args else {}
                print(f"🤖🔧 Ajan aracı: {fc.name} -> {args}")
                out = await self._exec_tool(fc.name, args)
                results.append({"function_response": {
                    "name": fc.name, "response": {"result": str(out)[:8000]}}})
            contents.append({"role": "user", "parts": results})
        return "Görev tamamlandı."
