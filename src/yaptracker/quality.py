"""How good is a reading of a chat line? (#195)

OCR's own confidence, minus the share of characters that can't be chat text (CJK and other
scripts from a sign behind the box). Measured on the 2026-10-01 samples: how bright the
background behind a line is does not predict a bad reading (coloured chat text is bright too),
so it isn't part of the score.
"""

from yaptracker.glyphs import GLYPH

GOOD = 0.9  # below this a line is read again while it's on screen


def _chat_character(ch: str) -> bool:
    """Latin letters with accents (German, French...), digits, punctuation, the icon mark."""
    return ord(ch) < 0x250 or ch == GLYPH or 0x2000 <= ord(ch) <= 0x206F


def reading_quality(text: str, confidence: float) -> float:
    shown = [ch for ch in text if not ch.isspace()]
    if not shown:
        return 0.0
    junk = sum(1 for ch in shown if not _chat_character(ch)) / len(shown)
    return max(0.0, min(1.0, confidence - junk))
