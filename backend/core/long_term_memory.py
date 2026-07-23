"""
Kalıcı hafıza deposu, Egemen'le ilgili bilgiyi kategorilere ayrılmış
Markdown dosyalarında tutar. Repo dışında (backend.config.MEMORY_DIR).
Spec: docs/superpowers/specs/2026-07-22-kalici-hafiza-design.md
"""
import re
from datetime import datetime
from pathlib import Path

# Her oturum başında TAM içeriğiyle sistem promptuna yüklenen kategoriler.
# Diğer kategoriler (ör. sonradan açılan konu dosyaları) sadece recall() ile aranır.
CORE_CATEGORIES = ("karakter-tercihler", "hakkimda", "ilgi-alanlarim")


class MemoryStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "digests").mkdir(exist_ok=True)
        self._index_path = self.base_dir / "MEMORY.md"

    def _category_path(self, category: str) -> Path:
        safe = category.strip().lower().replace(" ", "-")
        safe = re.sub(r"[^a-z0-9ığüşöçİĞÜŞÖÇ\-]", "", safe)
        safe = safe.strip("-") or "genel"
        return self.base_dir / f"{safe}.md"

    def save_fact(self, category: str, text: str) -> str:
        path = self._category_path(category)
        is_new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {category}\n\n")
            f.write(f"- {text}\n")
        if is_new:
            self._add_to_index(category, path.name)
        return f"Kaydedildi ({category}): {text}"

    def _add_to_index(self, category: str, filename: str):
        with self._index_path.open("a", encoding="utf-8") as f:
            f.write(f"- {category}\n")

    def append_digest(self, text: str, when: datetime | None = None) -> str:
        when = when or datetime.now()
        path = self.base_dir / "digests" / f"{when.strftime('%Y-%m-%d')}.md"
        is_new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# {when.strftime('%Y-%m-%d')}\n\n")
            f.write(f"## {when.strftime('%H:%M')}\n\n{text}\n\n")
        return f"Özet kaydedildi: {path.name}"

    def read_core_files(self) -> str:
        parts = []
        if self._index_path.exists():
            parts.append(self._index_path.read_text(encoding="utf-8"))
        for category in CORE_CATEGORIES:
            path = self._category_path(category)
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def add_todo(self, item: str) -> str:
        path = self.base_dir / "todos.md"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- [ ] {item}\n")
        return f"Yapılacaklara eklendi: {item}"

    def complete_todo(self, item: str) -> str:
        path = self.base_dir / "todos.md"
        if not path.exists():
            return f"'{item}' listede bulunamadı."
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("- [ ]") and item.lower() in line.lower():
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return f"Tamamlandı: {item}"
        return f"'{item}' listede bulunamadı."

    def read_todos(self) -> str:
        path = self.base_dir / "todos.md"
        if not path.exists():
            return "Yapılacaklar listesi boş."
        return path.read_text(encoding="utf-8")

    def search_digests(self, query: str) -> str:
        digests_dir = self.base_dir / "digests"
        query_lower = query.lower()
        matches = []
        for path in sorted(digests_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if query_lower in text.lower():
                matches.append(f"### {path.stem}\n{text}")
        if not matches:
            return f"'{query}' ile ilgili geçmiş kayıt bulunamadı."
        return "\n\n".join(matches[-5:])
