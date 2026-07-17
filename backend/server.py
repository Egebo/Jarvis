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
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import SERVER_HOST, SERVER_PORT
from backend.core.brain import JarvisBrain
from backend.core.stt import SpeechToText
from backend.core.tts import TextToSpeech
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

                await manager.send(client_id, {"type": "transcript", "data": transcript})
                await _process_message(client_id, transcript, brain, tts, executor)

            # ── Yazılı giriş ─────────────────────────────────────────────────
            elif msg_type == "text":
                text = msg.get("data", "").strip()
                if text:
                    log.info(f"💬 [{client_id}] '{text}'")
                    await _process_message(client_id, text, brain, tts, executor)

            # ── Hafıza sıfırlama ─────────────────────────────────────────────
            elif msg_type == "reset":
                brain.reset_memory()
                await manager.send(client_id, {"type": "status", "data": "reset"})
                log.info(f"🔄 [{client_id}] Hafıza sıfırlandı")

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        log.error(f"❌ [{client_id}] Hata: {e}", exc_info=True)
        await manager.send(client_id, {"type": "error", "data": str(e)})
        manager.disconnect(client_id)


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
