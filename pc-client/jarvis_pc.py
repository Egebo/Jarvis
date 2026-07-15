"""
Jarvis PC Client
Windows'ta çalışan masaüstü istemcisi.

Özellikler:
  - Wake word algılama ("Jarvis" dersen aktifleşir)
  - Mikrofon kaydı + sessizlik algılama
  - Sunucuya WebSocket ile bağlanır
  - Yanıtı hoparlörden çalar
  - Sistem tepsisinde (tray) çalışır

Kullanım:
  python pc-client/jarvis_pc.py
"""

import asyncio
import base64
import json
import logging
import struct
import sys
import threading
import time
import uuid
import wave
import io
from pathlib import Path

import pyaudio
import websockets

# Proje kökünü path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("jarvis-pc")

# ─── Ayarlar ────────────────────────────────────────────────────────────────
SERVER_URL = "ws://localhost:8765/ws"
CLIENT_ID = f"pc-{uuid.getnode()}"

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16

SILENCE_THRESHOLD = 600    # RMS eşiği — daha düşük = daha hassas
SILENCE_DURATION = 1.2     # Bu kadar sessizlik → kayıt bitti
MAX_RECORD_SECONDS = 12    # Maksimum kayıt süresi

WAKE_WORD = "jarvis"       # Tetikleyici kelime (basit string match)


# ─── Ses Yardımcıları ────────────────────────────────────────────────────────
def rms(data: bytes) -> float:
    """PCM verisinin RMS (ses seviyesi) değeri."""
    count = len(data) // 2
    if count == 0:
        return 0
    shorts = struct.unpack(f"{count}h", data)
    return (sum(s * s for s in shorts) / count) ** 0.5


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """Ham PCM → WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def play_audio_bytes(audio_bytes: bytes):
    """WAV veya MP3 bytes'ı hoparlörden çal."""
    try:
        # playsound veya simpleaudio ile çal
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        # Windows
        import subprocess
        subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{tmp}').PlaySync()"],
                       capture_output=True)
        os.unlink(tmp)
    except Exception as e:
        log.warning(f"Ses çalma hatası: {e}")


# ─── Ana Client Sınıfı ───────────────────────────────────────────────────────
class JarvisPCClient:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.ws = None
        self.is_listening = False
        self.is_active = False      # Wake word sonrası aktif mi?
        self.state = "idle"         # idle | listening | thinking | speaking
        self._recv_task = None

    # ── Bağlantı ─────────────────────────────────────────────────────────────
    async def connect(self):
        url = f"{SERVER_URL}/{CLIENT_ID}"
        log.info(f"🔗 Sunucuya bağlanıyor: {url}")
        while True:
            try:
                self.ws = await websockets.connect(url, ping_interval=30)
                log.info("✅ Bağlandı!")
                self._recv_task = asyncio.create_task(self._receive_loop())
                return
            except Exception as e:
                log.warning(f"Bağlantı başarısız ({e}), 3s sonra tekrar...")
                await asyncio.sleep(3)

    async def _receive_loop(self):
        """Sunucudan gelen mesajları işle."""
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                await self._handle_server_msg(msg)
        except websockets.ConnectionClosed:
            log.warning("Bağlantı koptu, yeniden bağlanıyor...")
            await asyncio.sleep(2)
            await self.connect()

    async def _handle_server_msg(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "status":
            self.state = msg["data"]
            icons = {"idle": "😴", "transcribing": "👂", "thinking": "🧠",
                     "speaking": "🔊", "reset": "🔄"}
            print(f"\r{icons.get(self.state, '?')} {self.state}       ", end="", flush=True)

        elif mtype == "transcript":
            print(f"\n🗣️  Sen: {msg['data']}")

        elif mtype == "response":
            print(f"\n🤖 Jarvis: {msg['data']}\n")

        elif mtype == "audio":
            audio_bytes = base64.b64decode(msg["data"])
            # Ayrı thread'de çal (async'i bloklamasın)
            threading.Thread(target=play_audio_bytes, args=(audio_bytes,), daemon=True).start()

        elif mtype == "error":
            log.error(f"Sunucu hatası: {msg['data']}")

    # ── Ses Kaydı ────────────────────────────────────────────────────────────
    def record_until_silence(self) -> bytes:
        """
        Sessizlik bitene kadar kaydet.
        Döndürür: ham PCM bytes
        """
        stream = self.pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        frames = []
        silence_chunks = 0
        required_silence = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK)
        max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK)

        print("\n🎙️  Dinliyorum...", end="", flush=True)

        for _ in range(max_chunks):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            level = rms(data)

            # Ses göstergesi
            bar = "█" * int(level / 200) + " " * 20
            print(f"\r🎙️  [{bar[:20]}]", end="", flush=True)

            if level < SILENCE_THRESHOLD:
                silence_chunks += 1
                if silence_chunks >= required_silence:
                    break
            else:
                silence_chunks = 0

        stream.stop_stream()
        stream.close()
        print("\r" + " " * 40 + "\r", end="")

        return b"".join(frames)

    _wake_model = None

    def _get_wake_model(self):
        """Wake word için tiny Whisper modelini BİR KEZ yükle (her turda değil)."""
        if JarvisPCClient._wake_model is None:
            import whisper
            log.info("🎙️  Wake word modeli yükleniyor (tiny)...")
            JarvisPCClient._wake_model = whisper.load_model("tiny")
            log.info("✅ Wake word modeli hazır")
        return JarvisPCClient._wake_model

    @staticmethod
    def _matches_wake_word(text: str) -> bool:
        """
        Whisper 'Jarvis'i Türkçe modunda türlü şekillerde yazabiliyor
        (carvis, çarvış, jarvıs...). Birebir eşleşme yerine bulanık eşleşme yap.
        """
        from difflib import SequenceMatcher
        text = text.lower().replace("ı", "i").replace("ş", "s").replace("ç", "c")
        if WAKE_WORD in text:
            return True
        for word in text.replace(",", " ").replace(".", " ").split():
            if SequenceMatcher(None, word, WAKE_WORD).ratio() >= 0.65:
                return True
        return False

    def _transcribe_tiny(self, pcm: bytes) -> str:
        """Lokal tiny model ile hızlı transkripsiyon (sadece wake word kontrolü için)."""
        import tempfile, os
        model = self._get_wake_model()
        wav = pcm_to_wav(pcm)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav)
            tmp = f.name
        try:
            result = model.transcribe(tmp, language="tr", fp16=False,
                                      initial_prompt="Jarvis")
            return result["text"].lower().strip()
        finally:
            os.unlink(tmp)

    def wait_for_command(self) -> bytes | None:
        """
        Tek nefeste komut akışı:
        Ses başlayana kadar bekle → konuşmanın TAMAMINI kaydet →
        'Jarvis' ile başlıyorsa/içeriyorsa tüm kaydı döndür (komut dahil).
        Böylece 'Jarvis, ekranımda ne var?' tek seferde çalışır;
        sadece 'Jarvis' denirse de kısa kayıt gider, sunucu 'Buyrun?' der.
        """
        import collections

        stream = self.pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        try:
            # 1) Ses başlayana kadar bekle (öncesinden 0.5s tampon tut ki
            #    'Jarvis'in J'si kırpılmasın)
            preroll = collections.deque(maxlen=int(0.5 * SAMPLE_RATE / CHUNK))
            waited_chunks = 0
            max_wait_chunks = int(10 * SAMPLE_RATE / CHUNK)   # 10s sessizlik → döngüye dön
            while True:
                data = stream.read(CHUNK, exception_on_overflow=False)
                preroll.append(data)
                if rms(data) >= SILENCE_THRESHOLD:
                    break
                waited_chunks += 1
                if waited_chunks > max_wait_chunks:
                    return None

            # 2) Konuşma bitene kadar kaydet
            frames = list(preroll)
            silence_chunks = 0
            required_silence = int(SILENCE_DURATION * SAMPLE_RATE / CHUNK)
            max_chunks = int(MAX_RECORD_SECONDS * SAMPLE_RATE / CHUNK)
            for _ in range(max_chunks):
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                if rms(data) < SILENCE_THRESHOLD:
                    silence_chunks += 1
                    if silence_chunks >= required_silence:
                        break
                else:
                    silence_chunks = 0
        finally:
            stream.stop_stream()
            stream.close()

        # 3) Wake word kontrolü — cümlenin başında/içinde 'jarvis' var mı?
        pcm = b"".join(frames)
        try:
            text = self._transcribe_tiny(pcm)
            log.debug(f"Duyulan: '{text}'")
            if self._matches_wake_word(text):
                return pcm
        except Exception as e:
            log.debug(f"Wake word STT hatası: {e}")
        return None

    # ── Ana Döngü ────────────────────────────────────────────────────────────
    async def run(self):
        await self.connect()
        print("\n" + "="*50)
        print("🤖 JARVIS AKTİF")
        print(f"   Wake word: '{WAKE_WORD}' deyin veya Enter'a basın")
        print(f"   Çıkmak için: Ctrl+C")
        print("="*50 + "\n")

        # Klavye girişi için ayrı thread
        asyncio.create_task(self._keyboard_input())

        # Sürekli dinle: 'Jarvis ...' ile başlayan konuşmayı tek seferde yakala
        while True:
            if self.state == "idle":
                pcm = await asyncio.get_event_loop().run_in_executor(
                    None, self.wait_for_command
                )
                if pcm:
                    print("⚡ Jarvis algılandı, komut gönderiliyor...")
                    self._beep()
                    await self._send_audio(pcm)
            else:
                await asyncio.sleep(0.1)

    async def _send_audio(self, pcm: bytes):
        """Ham PCM kaydı WAV olarak sunucuya gönder."""
        wav_bytes = pcm_to_wav(pcm)
        audio_b64 = base64.b64encode(wav_bytes).decode()
        if self.ws:
            await self.ws.send(json.dumps({
                "type": "audio",
                "data": audio_b64
            }))

    async def _handle_voice_activation(self):
        """Enter'a basıldı — wake word beklemeden kaydet ve gönder."""
        self._beep()
        pcm = await asyncio.get_event_loop().run_in_executor(
            None, self.record_until_silence
        )
        await self._send_audio(pcm)

    async def _keyboard_input(self):
        """Enter'a basınca manuel aktivasyon."""
        loop = asyncio.get_event_loop()
        while True:
            await loop.run_in_executor(None, input)
            if self.state == "idle":
                await self._handle_voice_activation()

    def _beep(self):
        """Kısa aktivasyon sesi."""
        try:
            import winsound
            winsound.Beep(880, 100)
        except Exception:
            pass

    def cleanup(self):
        self.pa.terminate()


# ─── Metin Modu (test için) ───────────────────────────────────────────────────
class JarvisTextClient:
    """Wake word olmadan sadece metin ile test et."""
    def __init__(self):
        self.ws = None

    async def run(self):
        url = f"{SERVER_URL}/{CLIENT_ID}-text"
        print(f"🔗 Bağlanıyor: {url}")
        self.ws = await websockets.connect(url)
        print("✅ Bağlandı! Mesaj yazın (çıkmak: 'q')\n")

        recv = asyncio.create_task(self._recv())

        while True:
            text = await asyncio.get_event_loop().run_in_executor(None, input, "Sen: ")
            if text.lower() in ("q", "quit", "çıkış"):
                break
            await self.ws.send(json.dumps({"type": "text", "data": text}))

        await self.ws.close()

    async def _recv(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg["type"] == "response":
                print(f"\n🤖 Jarvis: {msg['data']}\n")
            elif msg["type"] == "transcript":
                pass
            elif msg["type"] == "error":
                print(f"\n❌ {msg['data']}\n")


# ─── Giriş Noktası ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Jarvis PC Client")
    parser.add_argument("--text", action="store_true", help="Metin modu (test)")
    parser.add_argument("--server", default="ws://localhost:8765/ws", help="Sunucu URL")
    args = parser.parse_args()

    SERVER_URL = args.server

    try:
        if args.text:
            asyncio.run(JarvisTextClient().run())
        else:
            client = JarvisPCClient()
            asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\n👋 Jarvis kapatıldı.")
