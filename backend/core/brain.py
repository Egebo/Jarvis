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
                description="Hatırlatıcı veya alarm kurar.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Hatırlatıcı mesajı"},
                        "minutes": {"type": "integer", "description": "Kaç dakika sonra"}
                    },
                    "required": ["message", "minutes"]
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
                name="take_screenshot",
                description="Ekran görüntüsü alır ve içeriğini analiz eder.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                    "required": []
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
            system_instruction=SYSTEM_PROMPT,
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
