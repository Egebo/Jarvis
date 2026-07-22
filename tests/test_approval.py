import pytest
from backend.core.task_manager import parse_approval


@pytest.mark.parametrize("text", ["evet", "Evet.", "onayla", "onaylıyorum", "yap", "tamam", "evet yap lütfen"])
def test_approvals(text):
    assert parse_approval(text) is True


@pytest.mark.parametrize("text", ["hayır", "Hayır!", "iptal", "yapma", "dur", "hayır iptal et"])
def test_rejections(text):
    assert parse_approval(text) is False


@pytest.mark.parametrize("text", ["saat kaç", "hava nasıl bugün", "", "raporu sonra okurum"])
def test_unrelated(text):
    assert parse_approval(text) is None


def test_rejection_wins_when_both():
    # "yapma" içinde "yap" geçer; kelime bazlı eşleşme bunu RED saymalı
    assert parse_approval("yapma") is False


@pytest.mark.parametrize("text,expected", [
    ("tamam, sonra bakarız o işi", None),           # onay kelimesi var ama uzun cümle
    ("evet", True),
    ("tamam yap", True),
    ("bence de tamam ama once sunu konusalim", None),  # uzun, onay sayılmaz
    ("hayır bence bu çok riskli bir iş olur", False),  # red her uzunlukta çalışır
])
def test_approve_only_short_reject_any_length(text, expected):
    assert parse_approval(text) is expected
