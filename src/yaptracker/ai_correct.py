"""AI correction (#637): a doubtful chat line is re-read from its picture by a vision model.

What is sent: the line picture only (one chat row as #120 keeps it: icon, name, text), nothing
else from the screen, no DB data (Marv, 2026-11-26: names may go along in the picture). With the
user's own OpenRouter key, through the same routing as AI translation: zero data retention, no
data collection, never Google Vertex (#583). Off without a key; spends from the same monthly cap.

The #637 spike (200 hard lines): Claude Haiku 5.5 fixed 24 stored lines and broke 2, about
$0.00005 a line and ~1 s; Sonnet 5.5 is the fallback (more accurate, 26x the price, must think
a little). The cheap vision models broke as many lines as they fixed, so none of them.

This module asks and answers; the reader decides which lines to send (`triggers`) and stores
the answer as a second reading, never over a hand edit.
"""

import base64
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from yaptracker import ai_translate
from yaptracker.ai_translate import PROVIDER, URL, Spend
from yaptracker.days import day_of
from yaptracker.glyphs import GLYPH

log = logging.getLogger(__name__)

MODEL = "anthropic/claude-haiku-5.5"
FALLBACK = "anthropic/claude-sonnet-5.5"
THINKS = {FALLBACK}  # its endpoint refuses "no reasoning" (the spike: 400)
TIMEOUT_S = 8.0  # the spike: 2 s at most for Haiku, 5.5 s for Sonnet
EVENING_LIMIT = 300  # lines a night at most (#637); the monthly cap is the other brake
PROMPT = (
    "This picture is one row of Overwatch's in-game text chat. Transcribe it exactly, "
    "character by character: brackets, colons, punctuation, capitals, umlauts and ß as shown. "
    "Names and slang are spelled unusually on purpose: never correct spelling, never complete "
    "or translate anything. Leave out the small channel icon at the very start of the row. "
    "Where the row shows an emoji or a game icon, write ◇ in its place. "
    'Answer with JSON only: {"text": "<the row>", "icons": ["<what each ◇ shows, 1-3 words>"]}'
)


@dataclass
class Correction:
    row: str | None = None  # the whole row as the model read it ("[Name]: text")
    icons: list[str] = field(default_factory=list)  # what each ◇ shows, in words
    model: str | None = None
    error: str | None = None  # why there is none: ai_translate's messages


def request(key: str, model: str, png: bytes) -> urllib.request.Request:
    picture = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": picture}},
                ],
            }
        ],  # fmt: skip
        "provider": PROVIDER,
        "usage": {"include": True},
        "temperature": 0,
        "max_tokens": 300,
        "reasoning": ai_translate.LITTLE_THINKING if model in THINKS else ai_translate.NO_THINKING,
    }
    return urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "X-Title": "YapTracker"},
    )  # fmt: skip


def parse(content: str) -> tuple[str, list[str]]:
    """(row, icons) from the answer: its first JSON object (Haiku sometimes adds a remark after
    it), the channel icon some models write as a leading ◇ taken off."""
    if not isinstance(content, str) or "{" not in content:
        raise ValueError("no JSON in the answer")
    found, _ = json.JSONDecoder().raw_decode(content[content.find("{") :])
    row = found.get("text")
    if not isinstance(row, str) or not row.strip():
        raise ValueError("an answer without text")
    icons = [str(icon) for icon in found.get("icons") or [] if isinstance(icon, (str, int))]
    return " ".join(row.lstrip(GLYPH + " ").split()), icons


class Corrector:
    """Asks on the caller's thread (the reader's own correction thread, never capture or OCR).
    Default model first, the fallback when it fails; one request at a time, so the cap and the
    evening's limit are checked and counted together."""

    def __init__(self, key: Callable[[], str], cap: Callable[[], float], spend: Spend,
                 limit: Callable[[], int] = lambda: EVENING_LIMIT,
                 send: Callable[..., dict] = ai_translate._open,
                 clock: Callable[[], float] = time.time) -> None:  # fmt: skip
        self._key, self._cap, self.spend, self._limit = key, cap, spend, limit
        self._send, self._clock = send, clock
        self._sending = threading.Lock()
        self.evening: str | None = None
        self.sent_tonight = 0  # lines sent this evening, for Settings and the limit

    def correct(self, png: bytes) -> Correction:
        key = (self._key() or "").strip()
        if not key:
            return Correction(error=ai_translate.NO_KEY)
        with self._sending:
            tonight = day_of(self._clock())
            if tonight != self.evening:
                self.evening, self.sent_tonight = tonight, 0
            if self.sent_tonight >= self._limit():
                return Correction(error=f"Tonight's {self._limit()} lines are corrected: no more.")
            cap = self._cap()
            if self.spend.used() >= cap:
                return Correction(error=ai_translate.capped(cap))
            self.sent_tonight += 1
            first = self._ask(key, MODEL, png)
            if first.error is None or first.error in _FINAL:
                return first
            return self._ask(key, FALLBACK, png)

    def _ask(self, key: str, model: str, png: bytes) -> Correction:
        try:
            answer = self._send(request(key, model, png), TIMEOUT_S)
            self.spend.add(float((answer.get("usage") or {}).get("cost") or 0.0))
            row, icons = parse(answer["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as error:
            log.info("correct: OpenRouter said %s (%s)", error.code, model)
            return Correction(error=ai_translate._HTTP.get(error.code, ai_translate.FAILED))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log.info("correct: OpenRouter not reached (%s)", type(error).__name__)
            return Correction(error=ai_translate.OFFLINE)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            log.info("correct: odd answer from %s (%s)", model, type(error).__name__)
            return Correction(error=ai_translate.FAILED)
        return Correction(row=row, icons=icons, model=model)


# Asking the fallback won't help: the key, the credit or the cap is the problem, not the model.
_FINAL = {ai_translate.WRONG_KEY, ai_translate.NO_CREDIT}


# --- which lines are worth it (#637) -------------------------------------------------------
# Not OCR's confidence: the POC showed RapidOCR confidently wrong (85 of 10,776 lines < 0.9).
NEAR_NAME = 80  # fuzzy ratio to a known name, but not the name itself
SHORT = 3  # characters of text
EDITED_DAYS = 7  # a speaker whose line was fixed by hand this recently
_UMLAUT = re.compile(r"[äöüßÄÖÜ]")


def triggers(text: str, speaker: str | None, channel: str, *, readings_disagree: bool,
             wrapped: bool, known_names: list[str], edited_speakers: set[str],
             looks_german: Callable[[str], bool]) -> set[str]:  # fmt: skip
    """Why this stored line is doubtful, by #637's triggers; empty: not worth sending."""
    why = set()
    if readings_disagree:
        why.add("readings disagree")
    if speaker:
        name = speaker.lower()
        near = [n for n in known_names if n != name and fuzz.ratio(name, n) >= NEAR_NAME]
        if near and name not in known_names:
            why.add("name near-miss")
        if name in edited_speakers:
            why.add("speaker edited lately")
    if GLYPH in text or "[icon:" in text:
        why.add("icon")
    if channel != "system":
        if _UMLAUT.search(text) or looks_german(text):
            why.add("German")
        if len(text.strip()) <= SHORT:
            why.add("very short")
    if wrapped:
        why.add("wrapped")
    return why
