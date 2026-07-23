from datetime import datetime, timedelta
from backend.core.reminders import ReminderStore


def test_add_then_due_returns_past_reminder(tmp_path):
    store = ReminderStore(tmp_path)
    now = datetime(2026, 7, 23, 9, 0)
    store.add("Toplantıya git", now - timedelta(minutes=5))
    due = store.due(now)
    assert len(due) == 1
    assert due[0]["message"] == "Toplantıya git"


def test_due_excludes_future_reminder(tmp_path):
    store = ReminderStore(tmp_path)
    now = datetime(2026, 7, 23, 9, 0)
    store.add("Gelecekteki hatırlatıcı", now + timedelta(minutes=5))
    assert store.due(now) == []


def test_mark_fired_one_shot_marks_done_and_disappears_from_due(tmp_path):
    store = ReminderStore(tmp_path)
    now = datetime(2026, 7, 23, 9, 0)
    store.add("Su iç", now - timedelta(minutes=1))
    due = store.due(now)
    reminder_id = due[0]["id"]
    store.mark_fired(reminder_id)
    assert store.due(now) == []


def test_mark_fired_daily_recurrence_rolls_fire_at_forward_one_day(tmp_path):
    store = ReminderStore(tmp_path)
    now = datetime(2026, 7, 23, 9, 0)
    store.add("Sabah egzersizi", now, recurrence="daily")
    due = store.due(now)
    reminder_id = due[0]["id"]
    store.mark_fired(reminder_id, now=now)
    # Aynı gün artık due değil (bir sonraki güne kaydı)
    assert store.due(now) == []
    # Ertesi gün aynı saatte tekrar due
    next_day = now + timedelta(days=1)
    due_next_day = store.due(next_day)
    assert len(due_next_day) == 1
    assert due_next_day[0]["message"] == "Sabah egzersizi"


def test_mark_fired_daily_recurrence_catches_up_after_multi_day_downtime(tmp_path):
    # Sunucu birkaç gün kapalı kalıp yeniden başladığında (ör. 3 gün sonra),
    # hatırlatıcı tek 'due' taramasında bugüne kadar ileri sarılmalı - yoksa
    # ardışık zamanlayıcı tiklerinde art arda birkaç kez tetiklenir.
    store = ReminderStore(tmp_path)
    start = datetime(2026, 7, 20, 9, 0)
    store.add("Su iç", start, recurrence="daily")
    real_now = datetime(2026, 7, 23, 10, 0)  # 3 gün + 1 saat sonra
    due = store.due(real_now)
    reminder_id = due[0]["id"]
    store.mark_fired(reminder_id, now=real_now)
    # Geçmiş günlere ait tüm oluşumlar atlanmış olmalı, artık due değil
    assert store.due(real_now) == []
    # Bir sonraki geçerli oluşum 24 Temmuz 09:00 olmalı (23'ü değil, o da geçti)
    due_next = store.due(datetime(2026, 7, 24, 9, 0))
    assert len(due_next) == 1


def test_list_active_empty_store(tmp_path):
    store = ReminderStore(tmp_path)
    assert store.list_active() == "Aktif hatırlatıcı yok."


def test_list_active_non_empty_includes_message_and_time(tmp_path):
    store = ReminderStore(tmp_path)
    store.add("Doktora git", datetime(2026, 7, 24, 15, 30))
    result = store.list_active()
    assert "Doktora git" in result
    assert "24.07 15:30" in result


def test_cancel_fuzzy_match_case_insensitive(tmp_path):
    store = ReminderStore(tmp_path)
    store.add("Faturayı Öde", datetime(2026, 7, 24, 10, 0))
    msg = store.cancel("faturayı")
    assert "İptal edildi" in msg
    assert store.list_active() == "Aktif hatırlatıcı yok."


def test_cancel_no_match_returns_not_found_message(tmp_path):
    store = ReminderStore(tmp_path)
    store.add("Faturayı öde", datetime(2026, 7, 24, 10, 0))
    msg = store.cancel("alakasız bir metin")
    assert "bulunamadı" in msg
    # Mevcut hatırlatıcı hâlâ aktif kalmalı
    assert "Faturayı öde" in store.list_active()


def test_corrupt_reminders_json_falls_back_to_empty_store(tmp_path):
    path = tmp_path / "reminders.json"
    path.write_text("bu geçerli bir json değil {{{", encoding="utf-8")
    store = ReminderStore(tmp_path)
    assert store.list_active() == "Aktif hatırlatıcı yok."
    assert store.due(datetime(2026, 7, 23, 9, 0)) == []
    assert store.get_last_briefing_date() is None


def test_last_briefing_date_defaults_to_none(tmp_path):
    store = ReminderStore(tmp_path)
    assert store.get_last_briefing_date() is None


def test_last_briefing_date_round_trip(tmp_path):
    store = ReminderStore(tmp_path)
    store.set_last_briefing_date("2026-07-23")
    assert store.get_last_briefing_date() == "2026-07-23"
