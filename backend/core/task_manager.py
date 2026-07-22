"""
TaskManager: gorev yasam dongusu + sesli onay akisi.
Spec: docs/superpowers/specs/2026-07-22-gorev-ajani-design.md
"""
import re

APPROVE_WORDS = {"evet", "onayla", "onaylıyorum", "yap", "tamam"}
REJECT_WORDS = {"hayır", "hayir", "iptal", "yapma", "dur"}


def parse_approval(text: str) -> bool | None:
    """Kelime bazli onay/red algılama. Red kelimesi varsa RED kazanır."""
    words = set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))
    if words & REJECT_WORDS:
        return False
    if words & APPROVE_WORDS:
        return True
    return None
