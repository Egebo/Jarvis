"""
Jarvis Configuration
Tüm API anahtarları ve ayarlar .env dosyasından okunur.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ───────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")   # opsiyonel
PICOVOICE_API_KEY = os.getenv("PICOVOICE_API_KEY", "")     # wake word için

# ─── Gemini Ayarları ────────────────────────────────────────────────────────
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))

SYSTEM_PROMPT = """Sen Jarvis'sin — Egemen'in kişisel yapay zeka asistanı.
Iron Man'deki JARVIS gibi; zeki, hızlı, nazik ve yetenekli.

Temel kurallar:
- Türkçe konuşulduğunda Türkçe, İngilizce konuşulduğunda İngilizce yanıt ver
- Cevaplar kısa ve öz olsun — sözlü konuşma için yazıyorsun, uzun listeler değil
- Teknik sorularda detaylı ol ama günlük sohbette sade kal
- "Yapıyorum efendim", "Anlaşıldı" gibi kısa onaylar kullan
- Egemen'in tercihlerini ve alışkanlıklarını zamanla öğren ve hatırla
- Bilgisayar komutlarını, sistem bilgilerini ve interneti kullanabilirsin
- Samimi ve biraz mizahlı ol — robot gibi konuşma
"""

# ─── TTS Ayarları ───────────────────────────────────────────────────────────
TTS_ENGINE = os.getenv("TTS_ENGINE", "pyttsx3")        # "pyttsx3" veya "elevenlabs"
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam voice
TTS_RATE = int(os.getenv("TTS_RATE", "175"))           # Konuşma hızı (pyttsx3)
TTS_VOLUME = float(os.getenv("TTS_VOLUME", "0.9"))

# ─── STT Ayarları ───────────────────────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")     # tiny, base, small, medium, large
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "tr")         # tr veya en

# ─── Wake Word ──────────────────────────────────────────────────────────────
WAKE_WORD = os.getenv("WAKE_WORD", "jarvis")           # "jarvis", "hey jarvis", vs.
WAKE_WORD_SENSITIVITY = float(os.getenv("WAKE_WORD_SENSITIVITY", "0.7"))

# ─── Sunucu ─────────────────────────────────────────────────────────────────
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8765"))

# ─── Ses Ayarları ───────────────────────────────────────────────────────────
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
RECORD_SECONDS = 8          # Maksimum kayıt süresi
SILENCE_THRESHOLD = 500     # Sessizlik algılama eşiği
SILENCE_DURATION = 1.5      # Bu kadar sessizlik = konuşma bitti
