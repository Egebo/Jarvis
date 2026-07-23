"""
Jarvis Brain — Gemini API entegrasyonu
Konuşma hafızası ve araç çağrıları burada yönetilir.
"""
import base64

from google import genai
from google.genai import types
from backend.config import GEMINI_API_KEY, GEMINI_MODEL, MAX_TOKENS, SYSTEM_PROMPT
from backend.core.memory import ConversationMemory


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

    def _define_tools(self) -> list:
        """
        Gemini function-calling şeması. Her fonksiyon standart JSON Schema
        ile tanımlanır (parameters_json_schema) — Anthropic'teki input_schema
        ile birebir aynı formatta yazılabiliyor.
        """
        declarations = [
            types.FunctionDeclaration(
                name="web_search",
                description="İnternette arama yapar. Güncel bilgiler, haberler, hava durumu için kullan.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Arama sorgusu"}
                    },
                    "required": ["query"]
                }
            ),
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
            types.FunctionDeclaration(
                name="open_application",
                description="Bilgisayarda bir uygulama veya dosya açar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Uygulama adı (örn: 'Spotify', 'Chrome', 'VS Code')"},
                        "args": {"type": "string", "description": "Opsiyonel argümanlar", "default": ""}
                    },
                    "required": ["name"]
                }
            ),
            types.FunctionDeclaration(
                name="open_url",
                description="Tarayıcıda bir web sitesi/URL açar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Açılacak adres (örn: 'youtube.com')"}
                    },
                    "required": ["url"]
                }
            ),
            # NOT: run_command (PowerShell) aracı bilinçli olarak tanımlı değil —
            # STT yanlış anlarsa tehlikeli komut riski. executor.py'de kodu duruyor;
            # sesli onay mekanizmasıyla birlikte açılacak.
            types.FunctionDeclaration(
                name="system_info",
                description="Bilgisayar durumu hakkında bilgi alır (RAM, CPU, pil, disk).",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "enum": ["cpu", "memory", "battery", "disk", "network", "all"],
                            "description": "İstenen metrik"
                        }
                    },
                    "required": ["metric"]
                }
            ),
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
            types.FunctionDeclaration(
                name="get_weather",
                description="Hava durumu bilgisi alır.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "Şehir adı", "default": "Istanbul"}
                    },
                    "required": []
                }
            ),
            types.FunctionDeclaration(
                name="control_media",
                description="Müzik/video kontrolü yapar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["play", "pause", "next", "previous", "volume_up", "volume_down", "mute"],
                            "description": "Yapılacak işlem"
                        }
                    },
                    "required": ["action"]
                }
            ),
            types.FunctionDeclaration(
                name="get_now_playing",
                description=(
                    "Şu an çalan müzik/video adını ve açık pencere başlıklarını verir. "
                    "'Ne izliyorum', 'ne dinliyorum', 'bu şarkı ne' sorularında ÖNCE bunu kullan. "
                    "Netflix gibi DRM'li uygulamalar içerik adını gizler; o durumda dürüstçe söyle."
                ),
                parameters_json_schema={"type": "object", "properties": {}, "required": []}
            ),
            types.FunctionDeclaration(
                name="take_screenshot",
                description=(
                    "Ekran görüntüsü alır ve içeriğini analiz eder. "
                    "NOT: Netflix gibi DRM korumalı videolar görüntüde SİYAH çıkar; "
                    "'ne izliyorum' için get_now_playing kullan."
                ),
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            ),
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
        ]
        return [types.Tool(function_declarations=declarations)]

    def _build_contents(self) -> list:
        """Hafızadaki mesajları Gemini'nin Content/Part formatına çevirir."""
        contents = []
        for msg in self.memory.get_messages():
            role = msg["role"]
            content = msg["content"]

            if isinstance(content, str):
                contents.append(types.Content(role=role, parts=[types.Part(text=content)]))
            else:
                # Zaten Part listesi (fonksiyon çağrısı / fonksiyon sonucu)
                contents.append(types.Content(role=role, parts=list(content)))
        return contents

    async def think(self, user_message: str, tool_executor=None) -> str:
        """
        Kullanıcı mesajını işle, gerekirse araçları kullan, yanıt üret.
        """
        self.memory.add("user", user_message)

        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            max_output_tokens=MAX_TOKENS,
            tools=self.tools,
            # Sesli asistanda gecikme kritik: modelin cevap öncesi "düşünme"
            # aşamasını kapat (birkaç saniye kazandırır)
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        response = await self.client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=self._build_contents(),
            config=config,
        )

        # Fonksiyon çağrısı gerekiyor mu?
        while True:
            parts = response.candidates[0].content.parts or []
            function_calls = [p.function_call for p in parts if p.function_call]

            if not function_calls:
                break

            # Modelin fonksiyon çağrısı içeren yanıtını hafızaya ekle
            self.memory.add_raw("model", parts)

            function_response_parts = []
            for fc in function_calls:
                tool_name = fc.name
                tool_input = dict(fc.args) if fc.args else {}

                print(f"🔧 Araç kullanılıyor: {tool_name} → {tool_input}")

                if tool_executor:
                    result = await tool_executor(tool_name, tool_input)
                else:
                    result = f"Araç '{tool_name}' çalıştırılamadı."

                # Görsel içeren sonuç (örn. ekran görüntüsü): fonksiyon yanıtına
                # ek olarak görseli inline data olarak modele gönder
                if isinstance(result, dict) and "image_b64" in result:
                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result.get("text", "Görsel ekte.")}
                        )
                    )
                    function_response_parts.append(
                        types.Part.from_bytes(
                            data=base64.b64decode(result["image_b64"]),
                            mime_type=result.get("mime_type", "image/png"),
                        )
                    )
                else:
                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": str(result)}
                        )
                    )

            # Fonksiyon sonuçlarını hafızaya ekle ve devam et
            self.memory.add_raw("user", function_response_parts)

            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=self._build_contents(),
                config=config,
            )

        final_text = response.text or ""
        self.memory.add("model", final_text)
        return final_text

    def reset_memory(self):
        self.memory.clear()
        self.system_prompt = self._build_system_prompt()
