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
                # "auto"/boş → Whisper dili kendisi algılar (Türkçe, İngilizce...)
                # NOT: dil zorlamak + initial_prompt, yabancı dilde halüsinasyon
                # döngüsüne sokuyordu (22 Tem canlı testi) — ikisi de kaldırıldı
                language=self._language(),
                fp16=(self._device == "cuda"),
                condition_on_previous_text=False,
            )
            return _filter_hallucinated_segments(result)
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def _language():
        return None if STT_LANGUAGE in ("", "auto") else STT_LANGUAGE

    async def transcribe_file(self, file_path: str) -> str:
        self.load()
        result = self._model.transcribe(
            file_path,
            language=self._language(),
            fp16=(self._device == "cuda"),
        )
        return _filter_hallucinated_segments(result)


# Whisper, sessizlik/düşük seviyeli arka plan gürültüsünde konuşma yokken bile
# akıcı ama tamamen uydurma metin üretebiliyor (ör. "Thank you.", "Peel the
# chain" gibi - YouTube altyazısı tarzı eğitim verisinden sızan halüsinasyon,
# bilinen bir Whisper davranışı). no_speech_prob bunu yakalamıyor (model
# "konuşma var" diye eminmiş gibi davranıyor) ama avg_logprob (segmentin
# transkripsiyonuna ne kadar güvendiği) çok düşük çıkıyor. Gerçek konuşmada
# ölçülen avg_logprob ~-0.1, uydurma segmentlerde ~-3.7 (31 Tem 2026 testi) -
# aradaki boşluk geniş, -1.0 güvenli bir eşik.
HALLUCINATION_LOGPROB_THRESHOLD = -1.0

# Bazı halüsinasyonlar ("Thank you.", YouTube altyazı kalıntıları gibi)
# eğitim verisinde o kadar sık geçiyor ki model onları düşük ses/gürültüden
# bile YÜKSEK güvenle üretebiliyor (avg_logprob filtresi kaçırıyor). Bilinen,
# sık görülen halüsinasyon kalıpları için ayrıca bir liste (topluluk genelinde
# belgelenmiş bir Whisper davranışı; kendi log'larımızda da görüldü, 31 Tem 2026).
KNOWN_HALLUCINATIONS = {
    "thank you.", "thank you", "thanks for watching!", "thanks for watching",
    "thank you for watching!", "thank you for watching", "please subscribe",
    "subscribe", "bye.", "bye", "bye bye.", "www.youtube.com",
    "altyazı m.k.", "izlediğiniz için teşekkürler", "i'll see you next time.",
}


def _is_known_hallucination(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in KNOWN_HALLUCINATIONS


def _filter_hallucinated_segments(result: dict) -> str:
    segments = result.get("segments") or []
    if not segments:
        text = result.get("text", "").strip()
        return "" if _is_known_hallucination(text) else text
    kept = [s["text"] for s in segments
            if s.get("avg_logprob", 0.0) >= HALLUCINATION_LOGPROB_THRESHOLD
            and not _is_known_hallucination(s["text"])]
    return " ".join(kept).strip()


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
