"""
Oturum bitince (bağlantı kopması veya sıfırlama) konuşmadan kalıcı bilgi ve
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
    Oturum bittiğinde çağrılır. Konuşmadan digest ve kalıcı bilgi çıkarır,
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
