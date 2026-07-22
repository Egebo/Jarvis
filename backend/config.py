"""
Jarvis Configuration
Tüm API anahtarları ve ayarlar .env dosyasından okunur.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# NOT: GoodbyeDPI açıkken tüm Python HTTPS istekleri aralıklı olarak
# [SSL: INVALID_SESSION_ID] hatası verir. Jarvis'i kullanmadan önce
# GoodbyeDPI'ı kapatın veya blacklist moduna alın.

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
- ÇOK ÖNEMLİ: Yanıtın sesli okunacak. En fazla 1-2 kısa cümle kur.
  Liste yazma, paragraf yazma. Detay istenirse o zaman uzat.
- Teknik sorularda detaylı ol ama günlük sohbette sade kal
- "Yapıyorum efendim", "Anlaşıldı" gibi kısa onaylar kullan
- Egemen'in tercihlerini ve alışkanlıklarını zamanla öğren ve hatırla
- Bilgisayar komutlarını, sistem bilgilerini ve interneti kullanabilirsin
- Arka plan görevi hakkında soru gelirse (bitti mi, ne durumda) MUTLAKA
  task_status aracını çağır; görev durumu hakkında ASLA tahmin yürütme
- Samimi ve biraz mizahlı ol — robot gibi konuşma
"""

# ─── TTS Ayarları ───────────────────────────────────────────────────────────
TTS_ENGINE = os.getenv("TTS_ENGINE", "gemini")         # "gemini", "edge", "pyttsx3", "elevenlabs"
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GEMINI_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Charon")  # Puck, Charon, Kore, Fenrir, Orus...
GEMINI_TTS_STYLE = os.getenv(
    "GEMINI_TTS_STYLE",
    "Aşağıdaki metni Iron Man'deki JARVIS gibi sakin, kendinden emin, "
    "hafif esprili bir yapay zeka uşağı tonuyla, doğal Türkçe tonlamayla, "
    "akıcı ve hafif hızlı bir tempoyla oku"
)
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "tr-TR-AhmetNeural")  # ücretsiz nöral Türkçe ses
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+15%")     # Edge konuşma hızı ("+0%" = normal)
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

# ─── Görev Ajanı ────────────────────────────────────────────────────────────
from pathlib import Path

AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-3.5-flash")  # görev ajanı (sohbet: GEMINI_MODEL)
WORKSPACE_DIR = Path(os.getenv("JARVIS_WORKSPACE",
                               str(Path.home() / "Desktop" / "Jarvis-Workspace")))
APPROVAL_TIMEOUT = float(os.getenv("APPROVAL_TIMEOUT", "120"))  # sn; dolarsa RED
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "25"))
