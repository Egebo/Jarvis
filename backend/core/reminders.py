"""
Kalıcı hatırlatıcı deposu ve sabah bröfingi durumu. JSON dosyada tutulur,
repo dışında (backend.config.MEMORY_DIR). Sunucu kapansa/yeniden başlasa
bile hatırlatıcılar ve "bugün bröfing yapıldı mı" bilgisi kaybolmaz.
Spec: docs/superpowers/specs/2026-07-23-proaktiflik-design.md
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path


class ReminderStore:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.base_dir / "reminders.json"

    def _read(self) -> dict:
        if not self._path.exists():
            return {"reminders": [], "last_briefing_date": None}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"reminders": [], "last_briefing_date": None}

    def _write(self, data: dict):
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, message: str, fire_at: datetime, recurrence: str | None = None) -> str:
        data = self._read()
        data["reminders"].append({
            "id": str(uuid.uuid4()),
            "message": message,
            "fire_at": fire_at.isoformat(),
            "recurrence": recurrence,
            "done": False,
        })
        self._write(data)
        when = f"her gün {fire_at.strftime('%H:%M')}" if recurrence else fire_at.strftime("%d.%m %H:%M")
        return f"✅ Hatırlatıcı kuruldu ({when}): '{message}'"

    def due(self, now: datetime) -> list[dict]:
        data = self._read()
        return [r for r in data["reminders"]
                if not r["done"] and datetime.fromisoformat(r["fire_at"]) <= now]

    def mark_fired(self, reminder_id: str):
        data = self._read()
        for r in data["reminders"]:
            if r["id"] == reminder_id:
                if r["recurrence"] == "daily":
                    next_fire = datetime.fromisoformat(r["fire_at"]) + timedelta(days=1)
                    r["fire_at"] = next_fire.isoformat()
                else:
                    r["done"] = True
                break
        self._write(data)

    def list_active(self) -> str:
        data = self._read()
        active = [r for r in data["reminders"] if not r["done"]]
        if not active:
            return "Aktif hatırlatıcı yok."
        lines = []
        for r in active:
            when = datetime.fromisoformat(r["fire_at"]).strftime("%d.%m %H:%M")
            tag = " (her gün tekrarlar)" if r["recurrence"] == "daily" else ""
            lines.append(f"- {r['message']} — {when}{tag}")
        return "\n".join(lines)

    def cancel(self, query: str) -> str:
        data = self._read()
        query_lower = query.lower()
        for r in data["reminders"]:
            if not r["done"] and query_lower in r["message"].lower():
                r["done"] = True
                self._write(data)
                return f"İptal edildi: {r['message']}"
        return f"'{query}' ile eşleşen aktif hatırlatıcı bulunamadı."

    def get_last_briefing_date(self) -> str | None:
        return self._read().get("last_briefing_date")

    def set_last_briefing_date(self, date_str: str):
        data = self._read()
        data["last_briefing_date"] = date_str
        self._write(data)
