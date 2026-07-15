"""
Konuşma Hafızası — Jarvis kısa süreli belleği
"""
from collections import deque
from typing import Union


class ConversationMemory:
    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._history: deque = deque(maxlen=max_turns * 2)  # her tur 2 mesaj

    def add(self, role: str, content: str):
        """Basit metin mesajı ekle."""
        self._history.append({"role": role, "content": content})

    def add_raw(self, role: str, content):
        """Ham içerik ekle (araç kullanımı için)."""
        self._history.append({"role": role, "content": content})

    def get_messages(self) -> list:
        return list(self._history)

    def clear(self):
        self._history.clear()

    def summary(self) -> str:
        """Son 5 tur özeti."""
        recent = list(self._history)[-10:]
        lines = []
        for msg in recent:
            role = msg["role"].capitalize()
            content = msg["content"] if isinstance(msg["content"], str) else "[araç]"
            lines.append(f"{role}: {content[:100]}")
        return "\n".join(lines)
