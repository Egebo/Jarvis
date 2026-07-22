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
