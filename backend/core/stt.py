"""
Speech-to-Text — Whisper ile ses→metin dönüşümü
"""
import io
import tempfile
import os
import numpy as np
import whisper
from backend.config import WHISPER_MODEL, STT_LANGUAGE


class SpeechToText:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._device = "cpu"
        return cls._instance

    def load(self):
        """Modeli yükle (ilk çağrıda otomatik indirir). GPU varsa GPU kullanır."""
        if self._model is None:
            import torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"🎙️  Whisper modeli yükleniyor: {WHISPER_MODEL} ({self._device})")
            self._model = whisper.load_model(WHISPER_MODEL, device=self._device)
            print("✅ Whisper hazır!")

    async def transcribe_bytes(self, audio_bytes: bytes) -> str:
        """
        Ham ses verisini (PCM 16bit, 16kHz) metne çevirir.
        """
        self.load()

        # Geçici WAV dosyasına yaz
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
            # Basit WAV header ekle
            _write_wav(f, audio_bytes, sample_rate=16000)

        try:
            result = self._model.transcribe(
                tmp_path,
                language=STT_LANGUAGE,
                fp16=(self._device == "cuda"),
                condition_on_previous_text=False,
                # "Jarvis" gibi özel isimleri doğru yazması için modeli yönlendir
                initial_prompt="Jarvis adlı sesli asistanla Türkçe konuşma."
            )
            text = result["text"].strip()
            return text
        finally:
            os.unlink(tmp_path)

    async def transcribe_file(self, file_path: str) -> str:
        self.load()
        result = self._model.transcribe(
            file_path,
            language=STT_LANGUAGE,
            fp16=(self._device == "cuda"),
            initial_prompt="Jarvis adlı sesli asistanla Türkçe konuşma."
        )
        return result["text"].strip()


def _write_wav(f, pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16):
    """Minimal WAV dosyası yazar."""
    import struct
    data_size = len(pcm_bytes)
    f.write(b"RIFF")
    f.write(struct.pack("<I", 36 + data_size))
    f.write(b"WAVE")
    f.write(b"fmt ")
    f.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                        sample_rate * channels * bits // 8,
                        channels * bits // 8, bits))
    f.write(b"data")
    f.write(struct.pack("<I", data_size))
    f.write(pcm_bytes)
