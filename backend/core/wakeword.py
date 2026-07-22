"""
Wake word eşleştirme — Whisper transkriptlerindeki 'jarvis' yazım
tutarsızlıklarına (carvis, çarvış, jarvı...) karşı bulanık eşleştirme.
Hem PC client hem sunucu (web istemcileri için) aynı mantığı kullanır;
gerçek eşleştirme artık burada, tek yerde yapılır.
"""
from difflib import SequenceMatcher

from backend.config import WAKE_WORD


def matches_wake_word(text: str) -> bool:
    text = text.lower().replace("ı", "i").replace("ş", "s").replace("ç", "c")
    if WAKE_WORD in text:
        return True
    for word in text.replace(",", " ").replace(".", " ").split():
        if SequenceMatcher(None, word, WAKE_WORD).ratio() >= 0.65:
            return True
    return False
