from datetime import datetime, timedelta

import pytest

from backend.skills.executor import SkillExecutor

pytestmark = pytest.mark.asyncio


class FakeReminderStore:
    def __init__(self):
        self.added = []
        self.list_active_calls = 0
        self.cancelled = []

    def add(self, message, fire_at, recurrence=None):
        self.added.append({"message": message, "fire_at": fire_at, "recurrence": recurrence})
        return f"✅ Hatırlatıcı kuruldu: '{message}'"

    def list_active(self):
        self.list_active_calls += 1
        return "- Örnek hatırlatıcı — 23.07 10:00"

    def cancel(self, query):
        self.cancelled.append(query)
        return f"İptal edildi: {query}"


async def test_set_reminder_with_minutes_only_passes_correct_fire_at():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    before = datetime.now()
    reply = await ex.execute("set_reminder", {"message": "Kahve molası", "minutes": 10})
    after = datetime.now()

    assert "Hatırlatıcı kuruldu" in reply
    assert len(ex.reminder_store.added) == 1
    call = ex.reminder_store.added[0]
    assert call["message"] == "Kahve molası"
    assert call["recurrence"] is None
    assert before + timedelta(minutes=10) <= call["fire_at"] <= after + timedelta(minutes=10)


async def test_set_reminder_with_daily_at_only_sets_daily_recurrence_and_rolls_to_tomorrow():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    # "şu an - 1 dakika" seçildi: gerçek saatle çalışıldığında bu neredeyse
    # her zaman geçmişte kalır (yarına kaymayı tetikler). Ama gece yarısını
    # saran nadir bir an (ör. 00:00:30) bu varsayımı bozabilir - bu yüzden
    # beklenen sonuç, testin çalıştığı ana göre üretim koduyla AYNI mantıkla
    # yeniden hesaplanır, sabit "her zaman yarına kayar" varsayımına
    # güvenilmez (Faz 3 Task 3 review'ının bulduğu kırılganlık).
    past_moment = datetime.now() - timedelta(minutes=1)
    daily_at = past_moment.strftime("%H:%M")

    reply = await ex.execute("set_reminder", {"message": "Sabah egzersizi", "daily_at": daily_at})
    now_after = datetime.now()

    assert "Hatırlatıcı kuruldu" in reply
    assert len(ex.reminder_store.added) == 1
    call = ex.reminder_store.added[0]
    assert call["recurrence"] == "daily"
    assert call["fire_at"].hour == past_moment.hour
    assert call["fire_at"].minute == past_moment.minute

    today_candidate = now_after.replace(hour=past_moment.hour, minute=past_moment.minute,
                                        second=0, microsecond=0)
    expected_date = (now_after + timedelta(days=1)).date() if today_candidate <= now_after else now_after.date()
    assert call["fire_at"].date() == expected_date
    assert call["fire_at"] > now_after - timedelta(minutes=1)


async def test_set_reminder_with_both_minutes_and_daily_at_returns_error_and_store_untouched():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    reply = await ex.execute("set_reminder", {"message": "x", "minutes": 5, "daily_at": "09:00"})

    assert "Hem" in reply or "hem" in reply
    assert ex.reminder_store.added == []


async def test_set_reminder_with_neither_returns_error():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    reply = await ex.execute("set_reminder", {"message": "x"})

    assert ex.reminder_store.added == []
    assert "belirtmelisin" in reply


async def test_list_reminders_delegates():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    reply = await ex.execute("list_reminders", {})

    assert ex.reminder_store.list_active_calls == 1
    assert "Örnek hatırlatıcı" in reply


async def test_cancel_reminder_delegates():
    ex = SkillExecutor()
    ex.reminder_store = FakeReminderStore()
    reply = await ex.execute("cancel_reminder", {"query": "kahve"})

    assert ex.reminder_store.cancelled == ["kahve"]
    assert "İptal edildi" in reply


async def test_all_three_graceful_without_store():
    ex = SkillExecutor()
    calls = [
        ("set_reminder", {"message": "x", "minutes": 5}),
        ("list_reminders", {}),
        ("cancel_reminder", {"query": "x"}),
    ]
    for tool, args in calls:
        reply = await ex.execute(tool, args)
        assert "hazır değil" in reply
