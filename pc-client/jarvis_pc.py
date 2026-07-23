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

# 'Jarvis' geçiyor mu kontrolü artık SUNUCUDA yapılıyor (backend/core/
# wakeword.py) — hem PC hem web istemcisi aynı mantığı kullansın diye.
# Client burada sadece "ne zaman kaydedileceğine" karar verir.
from backend.config import WAKE_WORD


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
    """WAV bytes'ı hoparlörden çal (winsound: bellekten, süreç açmadan)."""
    try:
        import winsound
        winsound.PlaySound(audio_bytes, winsound.SND_MEMORY)
    except Exception as e:
        log.warning(f"Ses çalma hatası (winsound): {e}")
        # Yedek: eski PowerShell SoundPlayer yolu
        try:
            import tempfile, os, subprocess
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp = f.name
            subprocess.run(["powershell", "-c", f"(New-Object Media.SoundPlayer '{tmp}').PlaySync()"],
                           capture_output=True)
            os.unlink(tmp)
        except Exception as e2:
            log.error(f"Ses çalma tamamen başarısız: {e2}")


# ─── Ana Client Sınıfı ───────────────────────────────────────────────────────
class JarvisPCClient:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.ws = None
        self.is_listening = False
        self.is_active = False      # Wake word sonrası aktif mi?
        self.state = "idle"         # idle | listening | thinking | speaking
        self._recv_task = None
        self._playing = False       # Hoparlörden yanıt çalınıyor mu?
        # Sadece gösterim amaçlı — sunucudan 'followup' mesajı gelince
        # dolar. Gate kararı hâlâ tamamen sunucuda (backend/core/wakeword.py).
        self.followup_until = 0.0
        # Kalibrasyonla güncellenir (calibrate_noise)
        self.start_threshold = SILENCE_THRESHOLD
        self.end_threshold = SILENCE_THRESHOLD
        import queue
        self._audio_queue = queue.Queue()
        threading.Thread(target=self._audio_player_loop, daemon=True).start()

    def _audio_player_loop(self):
        """Ses parçalarını sırayla çal (cümle cümle gelirler, üst üste binmesinler)."""
        while True:
            audio = self._audio_queue.get()
            if audio is None:          # interrupt_playback'in bıraktığı boş işaret
                continue
            self._playing = True
            play_audio_bytes(audio)
            if self._audio_queue.empty():
                self._playing = False
                # Takip penceresi burada tahmin edilmiyor — sunucu 'followup'
                # mesajıyla açıldığını bildirene kadar hiçbir şey yazdırmıyoruz
                # (bkz. _handle_server_msg). Önceden burada her zaman "Jarvis
                # demeden konuşabilirsin" yazıyordu, sunucu gerçekten öyle
                # düşünmese bile — Egemen'in bulduğu sorun, 23 Tem 2026.

    def interrupt_playback(self):
        """Barge-in: çalan sesi kes, kuyruktaki bekleyenleri at."""
        import queue as _q
        try:
            while True:
                self._audio_queue.get_nowait()
        except _q.Empty:
            pass
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)   # çalanı durdur
        except Exception:
            pass
        self._playing = False

    # ── Bağlantı ─────────────────────────────────────────────────────────────
    async def connect(self):
        url = f"{SERVER_URL}/{CLIENT_ID}"
        log.info(f"🔗 Sunucuya bağlanıyor: {url}")
        while True:
            try:
                # max_size: uzun yanıtların ses parçaları 1MB varsayılan limiti
                # aşıp bağlantıyı sessizce düşürüyordu — ses hiç çalınmıyordu
                self.ws = await websockets.connect(url, ping_interval=30,
                                                   max_size=10 * 1024 * 1024)
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
            icon = icons.get(self.state, "?")
            label = self.state
            if self.state == "idle" and time.time() < self.followup_until:
                icon, label = "👂", "beklemede (Jarvis'siz konuşabilirsin)"
            print(f"\r{icon} {label}       ", end="", flush=True)

        elif mtype == "followup":
            self.followup_until = time.time() + float(msg["data"])
            print(f"\n👂 Beklemedeyim ({msg['data']:.0f}sn 'Jarvis' demeden konuşabilirsin)")

        elif mtype == "transcript":
            print(f"\n🗣️  Sen: {msg['data']}")

        elif mtype == "response":
            print(f"\n🤖 Jarvis: {msg['data']}\n")

        elif mtype == "audio":
            audio_bytes = base64.b64decode(msg["data"])
            # Kuyruğa ekle — çalma thread'i sırayla çalar
            self._audio_queue.put(audio_bytes)

        elif mtype == "ignored":
            print(f"\n🙉 (duydum ama 'Jarvis' demedin, yok saydım: '{msg['data']}')")

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

            if level < self.end_threshold:
                silence_chunks += 1
                if silence_chunks >= required_silence:
                    break
            else:
                silence_chunks = 0

        stream.stop_stream()
        stream.close()
        print("\r" + " " * 40 + "\r", end="")

        return b"".join(frames)

    def calibrate_noise(self):
        """
        1.5 saniye ortam sesi dinleyip eşikleri mikrofona göre ayarla.
        Sabit eşik (600) kimi mikrofonda çok yüksek kalıyordu — konuşma hiç
        algılanmıyordu.
        """
        stream = self.pa.open(format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                              input=True, frames_per_buffer=CHUNK)
        levels = []
        for _ in range(int(SAMPLE_RATE / CHUNK * 1.5)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            levels.append(rms(data))
        stream.stop_stream()
        stream.close()

        ambient = sorted(levels)[len(levels) // 2]   # medyan — ani seslerden etkilenmesin
        # Hassas eşikler: uzaktan konuşma da yakalansın. Yanlış tetiklenme
        # ucuz — 'jarvis' geçmeyen kayıtları tiny model zaten eliyor.
        self.start_threshold = max(80.0, ambient * 1.8)    # konuşma başladı eşiği
        self.end_threshold = max(60.0, ambient * 1.3)      # konuşma bitti eşiği
        log.info(f"🎚️  Mikrofon kalibrasyonu: ortam={ambient:.0f}, "
                 f"başlama eşiği={self.start_threshold:.0f}, bitiş eşiği={self.end_threshold:.0f}")

    def wait_for_command(self) -> tuple[bytes, bool] | None:
        """
        Ses başlayana kadar bekle (en fazla 10sn, yoksa çağıran tekrar dener) →
        konuşmanın TAMAMINI kaydet → ham PCM döndür.
        'Jarvis' geçip geçmediğine artık SUNUCU karar veriyor (backend/core/
        wakeword.py) — burada sadece ne zaman kayıt başlayıp biteceği belirlenir.

        İkinci dönüş değeri: kayıt BAŞLADIĞI anda (konuşmanın süresi değil,
        sadece bekleme anı) takip penceresi hâlâ açık mıydı. Bunu gönderim
        anında değil başlama anında ölçmek şart — uzun bir cümleyi kaydedip
        göndermek saniyeler sürebiliyor, o süre pencereyi dolduruyor ve
        sunucu tarafında yanlışlıkla gate'e takılabiliyordu (Egemen'in
        bulduğu sorun, 23 Tem 2026).
        """
        import collections

        stream = self.pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        was_in_followup = False
        try:
            # 1) Ses başlayana kadar bekle (öncesinden 0.5s tampon tut ki
            #    'Jarvis'in J'si kırpılmasın)
            preroll = collections.deque(maxlen=int(0.5 * SAMPLE_RATE / CHUNK))
            waited_chunks = 0
            voiced_streak = 0
            max_wait_chunks = int(10 * SAMPLE_RATE / CHUNK)
            while True:
                data = stream.read(CHUNK, exception_on_overflow=False)
                preroll.append(data)
                # Konuşma başladı sayılması için üst üste 3 sesli parça iste
                # (~200ms — eşik düştüğü için klik filtresini biraz sıkılaştır)
                if rms(data) >= self.start_threshold:
                    voiced_streak += 1
                    if voiced_streak >= 3:
                        was_in_followup = time.time() < self.followup_until
                        break
                else:
                    voiced_streak = 0
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
                if rms(data) < self.end_threshold:
                    silence_chunks += 1
                    if silence_chunks >= required_silence:
                        break
                else:
                    silence_chunks = 0
        finally:
            stream.stop_stream()
            stream.close()

        return b"".join(frames), was_in_followup

    # ── Ana Döngü ────────────────────────────────────────────────────────────
    async def run(self):
        await self.connect()
        # Mikrofon eşiklerini ortama göre ayarla
        await asyncio.get_event_loop().run_in_executor(None, self.calibrate_noise)
        print("\n" + "="*50)
        print("🤖 JARVIS AKTİF")
        print(f"   Wake word: '{WAKE_WORD}' deyin veya Enter'a basın")
        print(f"   Çıkmak için: Ctrl+C")
        print("="*50 + "\n")

        # Klavye girişi için ayrı thread
        asyncio.create_task(self._keyboard_input())

        # Sürekli dinle. 'Jarvis' geçip geçmediğine ve takip penceresine
        # sunucu karar verir; burada sadece ses algılanınca kaydedip yollarız.
        # Jarvis konuşurken dinlemiyoruz — kesme Enter ile yapılıyor (yukarıdaki
        # not: sesle kesme mikrofonun kendi hoparlörünü duyup karışıyordu).
        while True:
            if self.state == "idle" and not self._playing:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.wait_for_command
                )
                if result:
                    pcm, was_in_followup = result
                    print("⚡ Komut gönderiliyor...")
                    self._beep()
                    await self._send_audio(pcm, skip_gate=was_in_followup)
            else:
                await asyncio.sleep(0.1)

    async def _send_audio(self, pcm: bytes, skip_gate: bool = False):
        """
        Ham PCM kaydı WAV olarak sunucuya gönder.
        skip_gate: Enter'la manuel tetiklenen kayıtlarda True — kullanıcı
        niyetini zaten elle bildirdi, sunucu 'Jarvis' aramasın.
        """
        wav_bytes = pcm_to_wav(pcm)
        audio_b64 = base64.b64encode(wav_bytes).decode()
        if self.ws:
            await self.ws.send(json.dumps({
                "type": "audio",
                "data": audio_b64,
                "skip_gate": skip_gate,
            }))

    async def _handle_voice_activation(self):
        """Enter'a basıldı — wake word beklemeden kaydet ve gönder."""
        self._beep()
        pcm = await asyncio.get_event_loop().run_in_executor(
            None, self.record_until_silence
        )
        await self._send_audio(pcm, skip_gate=True)

    async def _keyboard_input(self):
        """
        Enter'a basınca manuel aktivasyon. Jarvis konuşurken basılırsa önce
        sesli kesme (barge-in) mikrofonun kendi hoparlörünü duyup karışması
        yüzünden güvenilir değil — Enter burada garantili, anında kesme sağlar.
        """
        loop = asyncio.get_event_loop()
        while True:
            await loop.run_in_executor(None, input)
            if self._playing:
                print("✋ Enter'a basıldı, konuşma kesiliyor...")
                self.interrupt_playback()
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
