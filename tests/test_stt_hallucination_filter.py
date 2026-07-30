from backend.core.stt import _filter_hallucinated_segments, _is_known_hallucination


def test_known_hallucination_phrase_detected_case_insensitive():
    assert _is_known_hallucination("Thank you.")
    assert _is_known_hallucination("  THANKS FOR WATCHING!  ")
    assert _is_known_hallucination("bye bye.")


def test_real_speech_not_flagged_as_hallucination():
    assert not _is_known_hallucination("Jarvis beni duyuyor musun?")
    assert not _is_known_hallucination("yarın saat 11'e randevu koy")


def test_filter_removes_known_hallucination_even_with_good_logprob():
    # Bazı halüsinasyonlar ("Thank you." gibi) o kadar sık geçiyor ki model
    # onları düşük logprob filtresini atlatacak kadar "güvenle" üretebiliyor -
    # denylist bunu ayrıca yakalamalı.
    result = {"segments": [{"text": "Thank you.", "avg_logprob": -0.1}]}
    assert _filter_hallucinated_segments(result) == ""


def test_filter_removes_low_logprob_segments():
    result = {"segments": [{"text": "Peel the chain", "avg_logprob": -3.7}]}
    assert _filter_hallucinated_segments(result) == ""


def test_filter_keeps_real_speech():
    result = {"segments": [{"text": "Jarvis nasılsın", "avg_logprob": -0.3}]}
    assert _filter_hallucinated_segments(result) == "Jarvis nasılsın"


def test_filter_keeps_only_valid_segments_when_mixed():
    result = {"segments": [
        {"text": "Thank you.", "avg_logprob": -0.59},
        {"text": "Jarvis nasılsın", "avg_logprob": -0.3},
        {"text": "Peel the chain", "avg_logprob": -3.7},
    ]}
    assert _filter_hallucinated_segments(result) == "Jarvis nasılsın"


def test_filter_falls_back_to_text_when_no_segments():
    result = {"text": "  merhaba  "}
    assert _filter_hallucinated_segments(result) == "merhaba"


def test_filter_empty_segments_list_returns_empty():
    result = {"segments": []}
    assert _filter_hallucinated_segments(result) == ""
