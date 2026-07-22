"""
Jarvis Ana Sunucu — FastAPI + WebSocket
PC client, web arayüzü ve (varsa) mobil clientların bağlandığı merkezi beyin.

HTTP:
  GET /            → Web arayüzü (backend/static/index.html)
  GET /static/...   → Statik dosyalar
  GET /api/status   → {"status": "online", "clients": N}
  GET /health       → {"status": "ok", "active_sessions": N}

WebSocket Protokolü (/ws/{client_id}):
  Client → Server: {"type": "audio", "data": "<base64 ham PCM, 16bit/16kHz/mono>"}
                   {"type": "text", "data": "mesaj"}
                   {"type": "reset"}
  Server → Client: {"type": "transcript", "data": "kullanıcı ne dedi"}
                   {"type": "response", "data": "Jarvis'in yanıtı"}
                   {"type": "audio", "data": "<base64 WAV>"}
                   {"type": "status", "data": "transcribing|thinking|speaking|idle|reset"}
                   {"type": "error", "data": "hata mesajı"}
"""

import asyncio
import base64
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import SERVER_HOST, SERVER_PORT, FOLLOWUP_WINDOW, MEMORY_DIR
from backend.core.brain import JarvisBrain
from backend.core.stt import SpeechToText
from backend.core.tts import TextToSpeech
from backend.core.wakeword import matches_wake_word
from backend.skills.executor import SkillExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("jarvis")

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ─── Uygulama Ömrü ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🤖 Jarvis başlatılıyor...")
    # STT modelini önceden yükle
    app.state.stt = SpeechToText()
    app.state.stt.load()
    app.state.tts = TextToSpeech()
    app.state.executor = SkillExecutor()

    from backend.core.task_manager import TaskManager

    async def task_event(event_type: str, message: str):
        """Görev olaylarını tüm clientlara duyur + sesli oku."""
        await manager.broadcast({"type": "task_update",
                                 "data": {"event": event_type, "message": message}})
        # "started" burada seslendirilmiyor: sohbet beynindeki "Başlıyorum efendim..."
        # zaten tek sözlü başlangıç anonsu olarak okunuyor; ikisi birden çakışmasın.
        speech = {
            "approval_request": f"Onayına ihtiyacım var efendim: {message}. Onaylıyor musun?",
            "done": message,
            "failed": message,
        }.get(event_type)
        if speech:
            await manager.broadcast({"type": "response", "data": speech})
            sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", speech) if s.strip()] or [speech]
            for sentence in sentences:
                audio_bytes = await app.state.tts.synthesize(sentence)
                await manager.broadcast({"type": "audio",
                                         "data": base64.b64encode(audio_bytes).decode()})

    app.state.task_manager = TaskManager(event_cb=task_event)
    app.state.executor.task_manager = app.state.task_manager

    from backend.core.long_term_memory import MemoryStore
    app.state.memory_store = MemoryStore(MEMORY_DIR)
    app.state.executor.memory_store = app.state.memory_store

    log.info("✅ Jarvis hazır! Bağlantı bekleniyor...")
    yield
    log.info("👋 Jarvis kapatılıyor...")


app = FastAPI(title="Jarvis", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Bağlantı Yöneticisi ────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.active[client_id] = ws
        log.info(f"🔗 Bağlandı: {client_id} (toplam: {len(self.active)})")

    def disconnect(self, client_id: str):
        self.active.pop(client_id, None)
        log.info(f"🔌 Ayrıldı: {client_id}")

    async def send(self, client_id: str, data: dict):
        ws = self.active.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except RuntimeError:
                # Bağlantı bu arada kapandıysa sunucuyu düşürme
                self.disconnect(client_id)

    async def broadcast(self, data: dict):
        for ws in self.active.values():
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                pass


manager = ConnectionManager()


# ─── Oturum Yönetimi ────────────────────────────────────────────────────────
sessions: dict[str, JarvisBrain] = {}
# Yanıttan sonraki kısa pencerede wake word'süz devam edilebilsin diye
# (client_id -> bu zamana kadar geçerli). Sadece sesli girişte kullanılır;
# yazılı mesajlar zaten niyet bildirdiği için hiç gate'lenmez.
followup_until: dict[str, float] = {}

def get_brain(client_id: str) -> JarvisBrain:
    if client_id not in sessions:
        sessions[client_id] = JarvisBrain()
    return sessions[client_id]


# ─── WebSocket Endpoint ──────────────────────────────────────────────────────
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(client_id, websocket)
    brain = get_brain(client_id)
    stt: SpeechToText = app.state.stt
    tts: TextToSpeech = app.state.tts
    executor: SkillExecutor = app.state.executor

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")

            # ── Sesli giriş ──────────────────────────────────────────────────
            if msg_type == "audio":
                audio_bytes = base64.b64decode(msg["data"])
                await manager.send(client_id, {"type": "status", "data": "transcribing"})

                transcript = await stt.transcribe_bytes(audio_bytes)
                log.info(f"📝 [{client_id}] '{transcript}'")

                if not transcript.strip():
                    await manager.send(client_id, {"type": "status", "data": "idle"})
                    continue

                tm = app.state.task_manager
                # Onaylar yalnızca PC istemcisinden (Egemen kararı, 22 Tem 2026)
                if tm.waiting_approval and client_id.startswith("pc-"):
                    ack = await tm.handle_utterance(transcript)
                    if ack:
                        await _speak_short(client_id, ack)
                        continue

                # Wake word gate: 'Jarvis' geçmiyorsa ve takip penceresinde
                # değilsek sessizce yok say — odadaki alakasız konuşmalar
                # (TV, sohbet) komut sanılmasın. Gate hem PC hem web istemcisi
                # için tek yerde (backend/core/wakeword.py) uygulanır.
                # skip_gate: PC client'ta Enter'la manuel tetiklenen kayıtlar
                # için — kullanıcı zaten niyetini elle bildirdi, 'Jarvis'
                # demesine gerek yok (yazılı mesajla aynı mantık).
                skip_gate = bool(msg.get("skip_gate"))
                in_followup = time.time() < followup_until.get(client_id, 0.0)
                if not skip_gate and not in_followup and not matches_wake_word(transcript):
                    # 'ignored' ayrı bir mesaj tipi: durum makinesini (idle)
                    # bozmadan istemciye 'duydum ama sana değildi' geri bildirimi
                    # verir — kullanıcı 'anladı mı anlamadı mı' diye kafası
                    # karışmasın diye (Egemen'in isteği, 22 Tem 2026).
                    await manager.send(client_id, {"type": "ignored", "data": transcript})
                    await manager.send(client_id, {"type": "status", "data": "idle"})
                    continue

                await manager.send(client_id, {"type": "transcript", "data": transcript})
                await _process_message(client_id, transcript, brain, tts, executor)
                followup_until[client_id] = time.time() + FOLLOWUP_WINDOW
                # İstemciye takip penceresinin açıldığını bildir — bu olmadan
                # istemci (web arayüzü/PC client) gerçekte 'Jarvis' demeden
                # konuşulabilecek bir an olduğunu bilemiyordu, hep aynı sabit
                # metni gösteriyordu (Egemen'in bulduğu sorun, 23 Tem 2026).
                await manager.send(client_id, {"type": "followup", "data": FOLLOWUP_WINDOW})

            # ── Yazılı giriş ─────────────────────────────────────────────────
            elif msg_type == "text":
                text = msg.get("data", "").strip()
                if text:
                    log.info(f"💬 [{client_id}] '{text}'")

                    tm = app.state.task_manager
                    # Onaylar yalnızca PC istemcisinden (Egemen kararı, 22 Tem 2026)
                    if tm.waiting_approval and client_id.startswith("pc-"):
                        ack = await tm.handle_utterance(text)
                        if ack:
                            await _speak_short(client_id, ack)
                            continue

                    await _process_message(client_id, text, brain, tts, executor)

            # ── Hafıza sıfırlama ─────────────────────────────────────────────
            elif msg_type == "reset":
                # Sıfırlamadan ÖNCE anlık kopya al (get_messages() yeni bir liste
                # döndürür) - arka plan görevi çalışırken brain.memory temizlenmiş
                # olabilir, canlı referans yerine kopya kullanılır.
                messages_snapshot = brain.memory.get_messages()
                asyncio.create_task(_save_session_memory(messages_snapshot, app.state.memory_store))
                brain.reset_memory()
                await manager.send(client_id, {"type": "status", "data": "reset"})
                log.info(f"🔄 [{client_id}] Hafıza sıfırlandı")

    except WebSocketDisconnect:
        manager.disconnect(client_id)
        messages_snapshot = brain.memory.get_messages()
        asyncio.create_task(_save_session_memory(messages_snapshot, app.state.memory_store))
    except Exception as e:
        log.error(f"❌ [{client_id}] Hata: {e}", exc_info=True)
        await manager.send(client_id, {"type": "error", "data": str(e)})
        manager.disconnect(client_id)


async def _save_session_memory(messages: list, store):
    """Oturum bittiğinde (kopma/sıfırlama) arka planda konuşmayı özetler.
    Kendi try/except'i var - burada patlayan hiçbir şey sunucuyu etkilemez."""
    from backend.core.memory_digest import summarize_and_save
    try:
        await summarize_and_save(messages, store)
    except Exception as e:
        log.warning(f"Hafıza özetleme başarısız: {e}")


async def _speak_short(client_id: str, text: str):
    """Kısa onay yanıtı: metin + tek parça ses."""
    await manager.send(client_id, {"type": "response", "data": text})
    tts: TextToSpeech = app.state.tts
    audio_bytes = await tts.synthesize(text)
    await manager.send(client_id, {"type": "audio",
                                   "data": base64.b64encode(audio_bytes).decode()})
    await manager.send(client_id, {"type": "status", "data": "idle"})


async def _process_message(
    client_id: str,
    text: str,
    brain: JarvisBrain,
    tts: TextToSpeech,
    executor: SkillExecutor
):
    """Metni işle, yanıt üret, sese çevir, gönder."""
    await manager.send(client_id, {"type": "status", "data": "thinking"})

    try:
        # Gemini'den yanıt al
        response = await brain.think(
            text,
            tool_executor=executor.execute
        )

        log.info(f"🤖 [{client_id}] → '{response[:80]}...'")

        # Yanıtı gönder
        await manager.send(client_id, {"type": "response", "data": response})
        await manager.send(client_id, {"type": "status", "data": "speaking"})

        # Cümle cümle seslendir: ilk cümle hazır olur olmaz çalmaya başlar,
        # kalanlar o çalarken sentezlenir (bekleme hissini azaltır)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", response) if s.strip()]
        if not sentences:
            sentences = [response]
        for sentence in sentences:
            audio_bytes = await tts.synthesize(sentence)
            audio_b64 = base64.b64encode(audio_bytes).decode()
            await manager.send(client_id, {"type": "audio", "data": audio_b64})

    except Exception as e:
        log.error(f"İşleme hatası: {e}", exc_info=True)
        await manager.send(client_id, {"type": "error", "data": f"Bir hata oluştu: {e}"})
    finally:
        await manager.send(client_id, {"type": "status", "data": "idle"})


# ─── HTTP Endpoints ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    """Web arayüzünü (backend/static/index.html) sunar."""
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/status")
async def api_status():
    return {"status": "online", "clients": len(manager.active)}

@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": len(sessions)}


# Web arayüzünün statik dosyaları (CSS/JS ileride ayrılırsa buradan servis edilir)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Çalıştır ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "backend.server:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=False,
        log_level="info"
    )
