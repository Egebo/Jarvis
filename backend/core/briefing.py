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
