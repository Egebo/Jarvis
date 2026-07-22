"""
Text-to-Speech — Metni sese çevirir
Desteklenen motorlar:
  - gemini    : Gemini TTS (Gemini API anahtarıyla, doğal tonlama, stil yönlendirilebilir) — varsayılan
  - edge      : Microsoft Edge TTS (ücretsiz, online, nöral sesler)
  - pyttsx3   : offline yedek (robotik SAPI sesi)
  - elevenlabs: yüksek kalite, ayrı API anahtarı gerekir
Hata durumunda sırayla bir alttaki motora düşülür: gemini → edge → pyttsx3
"""
import asyncio
import io
import subprocess
import threading
import time
import wave
from backend.config import (TTS_ENGINE, TTS_RATE, TTS_VOLUME, EDGE_TTS_VOICE,
                              EDGE_TTS_RATE,
                              GEMINI_API_KEY, GEMINI_TTS_MODEL, GEMINI_TTS_VOICE,
                              GEMINI_TTS_STYLE,
                              ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)


class TextToSpeech:
    def __init__(self):
        self.engine_name = TTS_ENGINE
        self._pyttsx3_engine = None
        self._gemini_client = None
        self._gemini_blocked_until = 0.0   # kota dolunca bu zamana kadar gemini'yi atla
        self._lock = threading.Lock()

    def _get_pyttsx3(self):
        if self._pyttsx3_engine is None:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", TTS_RATE)
            engine.setProperty("volume", TTS_VOLUME)
            # Türkçe ses varsa seç
            voices = engine.getProperty("voices")
            for voice in voices:
                if "turkish" in voice.name.lower() or "tr" in voice.id.lower():
                    engine.setProperty("voice", voice.id)
                    break
            self._pyttsx3_engine = engine
        return self._pyttsx3_engine

    async def synthesize(self, text: str) -> bytes:
        """
        Metni ses verisine çevirir (WAV bytes döndürür).
        """
        if self.engine_name == "elevenlabs" and ELEVENLABS_API_KEY:
            return await self._elevenlabs(text)
        if self.engine_name == "gemini" and time.time() >= self._gemini_blocked_until:
            try:
                return await self._gemini(text)
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    # Ücretsiz katman: günde 10 istek. Doldu — 1 saat deneme,
                    # her cümlede 429 beklemek gecikmeyi katlıyor.
                    self._gemini_blocked_until = time.time() + 3600
                    print("⚠️ Gemini TTS günlük kotası doldu — 1 saat Edge TTS kullanılacak")
                else:
                    print(f"⚠️ Gemini TTS hatası ({err[:120]}), Edge TTS'e düşülüyor")
        if self.engine_name in ("gemini", "edge"):
            try:
                return await self._edge(text)
            except Exception as e:
                print(f"⚠️ Edge TTS hatası ({e}), pyttsx3'e düşülüyor")
        return await self._pyttsx3(text)

    async def _gemini(self, text: str) -> bytes:
        """Gemini TTS — stil yönlendirmeli, doğal tonlamalı ses (WAV döndürür)."""
        from google import genai
        from google.genai import types

        if self._gemini_client is None:
            self._gemini_client = genai.Client(api_key=GEMINI_API_KEY)

        response = await self._gemini_client.aio.models.generate_content(
            model=GEMINI_TTS_MODEL,
            contents=f"{GEMINI_TTS_STYLE}: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_TTS_VOICE
                        )
                    )
                ),
            ),
        )

        # Ham PCM (16-bit, 24kHz, mono) döner — WAV kabına sar
        pcm = response.candidates[0].content.parts[0].inline_data.data
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)
        return buf.getvalue()

    async def _edge(self, text: str) -> bytes:
        """Edge TTS ile nöral Türkçe ses üretir (MP3 → WAV çevrilir)."""
        import edge_tts

        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE, rate=EDGE_TTS_RATE)
        mp3_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_data += chunk["data"]

        if not mp3_data:
            raise RuntimeError("Edge TTS boş ses döndürdü")

        # PC client'ın SoundPlayer'ı yalnızca WAV çalabiliyor → ffmpeg ile çevir
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._mp3_to_wav, mp3_data)

    @staticmethod
    def _mp3_to_wav(mp3_data: bytes) -> bytes:
        # ffmpeg pipe'a WAV yazarken RIFF boyut alanlarını dolduramıyor (seek yok);
        # winsound/SoundPlayer böyle başlığı reddediyor ve client sessiz kalıyordu.
        # Ham PCM alıp WAV başlığını burada düzgün yazıyoruz.
        proc = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le",
             "-ar", "24000", "-ac", "1", "pipe:1"],
            input=mp3_data, capture_output=True
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg dönüşüm hatası: {proc.stderr[-200:].decode(errors='ignore')}")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(proc.stdout)
        return buf.getvalue()

    async def speak(self, text: str):
        """
        Metni doğrudan hoparlörden çalar (PC için).
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._speak_sync, text)

    def _speak_sync(self, text: str):
        with self._lock:
            engine = self._get_pyttsx3()
            engine.say(text)
            engine.runAndWait()

    async def _pyttsx3(self, text: str) -> bytes:
        """pyttsx3 ile WAV bytes üretir."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_to_file, text, tmp_path)

        with open(tmp_path, "rb") as f:
            data = f.read()
        os.unlink(tmp_path)
        return data

    def _save_to_file(self, text: str, path: str):
        with self._lock:
            engine = self._get_pyttsx3()
            engine.save_to_file(text, path)
            engine.runAndWait()

    async def _elevenlabs(self, text: str) -> bytes:
        """ElevenLabs API ile yüksek kaliteli ses üretir."""
        import httpx

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8
            }
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.content
