"""
Text-to-Speech — Metni sese çevirir
Desteklenen motorlar: pyttsx3 (ücretsiz, offline) veya ElevenLabs (kaliteli, online)
"""
import io
import asyncio
import threading
from backend.config import (TTS_ENGINE, TTS_RATE, TTS_VOLUME,
                              ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)


class TextToSpeech:
    def __init__(self):
        self.engine_name = TTS_ENGINE
        self._pyttsx3_engine = None
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
        Metni ses verisine çevirir (MP3 bytes döndürür).
        """
        if self.engine_name == "elevenlabs" and ELEVENLABS_API_KEY:
            return await self._elevenlabs(text)
        else:
            return await self._pyttsx3(text)

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
