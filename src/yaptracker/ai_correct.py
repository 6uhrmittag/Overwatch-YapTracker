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
import http.client
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
from rapidfuzz import fuzz

from yaptracker import ai_translate, glyphs, icons, images
from yaptracker.ai_translate import PROVIDER, URL, Spend
from yaptracker.capture.source import Region
from yaptracker.days import day_of
from yaptracker.glyphs import GLYPH
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse as parse_chat

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
        "max_tokens": 1300 if model in THINKS else 300,  # thinking counts against it
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
    row = " ".join(row.lstrip(GLYPH + " ").split())
    if not row:  # only the channel icon: nothing read
        raise ValueError("an answer without text")
    icons = found.get("icons") or []
    icons = [icons] if isinstance(icons, str) else icons if isinstance(icons, list) else []
    return row, [str(icon) for icon in icons if isinstance(icon, (str, int))]


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
            got = self._ask(key, MODEL, png)
            if got.error is not None and got.error not in _FINAL:
                if self.spend.used() >= cap:  # the first answer may have used the rest
                    return Correction(error=ai_translate.capped(cap))
                got = self._ask(key, FALLBACK, png)
            if got.error != ai_translate.OFFLINE:  # what reached OpenRouter counts (and costs)
                self.sent_tonight += 1
            return got

    def _ask(self, key: str, model: str, png: bytes) -> Correction:
        timeout = ai_translate.THINKING_TIMEOUT_S if model in THINKS else TIMEOUT_S
        try:
            answer = self._send(request(key, model, png), timeout)
            self.spend.add(float((answer.get("usage") or {}).get("cost") or 0.0))
            row, named = parse(answer["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as error:
            log.info("correct: OpenRouter said %s (%s)", error.code, model)
            return Correction(error=ai_translate._HTTP.get(error.code, ai_translate.FAILED))
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as error:  # fmt: skip
            log.info("correct: OpenRouter not reached (%s)", type(error).__name__)
            if isinstance(error, TimeoutError) or "timed out" in str(error):
                self.spend.add(COST_GUESS.get(model, ai_translate.UNKNOWN_COST))  # billed anyway
                return Correction(error=TIMED_OUT)
            return Correction(error=ai_translate.OFFLINE)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            log.info("correct: odd answer from %s (%s)", model, type(error).__name__)
            return Correction(error=ai_translate.FAILED)
        return Correction(row=row, icons=named, model=model)


TIMED_OUT = "The AI took too long with this line."
COST_GUESS = {MODEL: 0.0001, FALLBACK: 0.0026}  # US dollars: twice what a line cost in the spike
# Asking the fallback won't help: the key, the credit, the network is the problem, not the model.
_FINAL = {ai_translate.WRONG_KEY, ai_translate.NO_CREDIT, ai_translate.OFFLINE}


# --- which lines are worth it (#637) -------------------------------------------------------
# Not OCR's confidence: the POC showed RapidOCR confidently wrong (85 of 10,776 lines < 0.9).
NEAR_NAME = 80  # fuzzy ratio to a known name, but not the name itself
SHORT = 3  # characters of text
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


# --- the worker: behind storing, never in the reader's way (#637) -------------------------
DELAY_S = 1.0  # a stored line waits this long: dedup may still find a better OCR reading
QUEUE_MAX = 60  # lines waiting at most; a flood drops the oldest (they stay as OCR read them)


@dataclass
class Waiting:
    message_id: int
    ts: float
    why: frozenset[str]
    since: float


class Worker:
    """Its own thread: takes doubtful stored lines, sends their picture, stores the AI's reading
    as a second reading. Capture and the reader only append to the queue and never wait.

    `relink(speaker, ts)` gives the player for a corrected name; `saved(message_id)` tells the
    UI; `label(entry)` keeps the correction for training (#608)."""

    def __init__(self, corrector: Corrector, store, picture: Callable[[int, float], object],
                 relink: Callable[[str | None, float], int | None],
                 saved: Callable[[int], None] = lambda message_id: None,
                 label: Callable[[dict], None] = lambda entry: None,
                 enabled: Callable[[], bool] = lambda: True,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._corrector, self._store, self._picture = corrector, store, picture
        self._relink, self._saved, self._label = relink, saved, label
        self._enabled, self._clock = enabled, clock
        self._lock = threading.Lock()
        self._queue: list[Waiting] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.counts: dict[str, int] = {}  # trigger -> lines sent this run, for the log
        self.corrected = 0  # lines whose reading the AI changed this run
        self._thread: threading.Thread | None = None

    def submit(self, message_id: int, ts: float, why: set[str]) -> None:
        if not why or not self._enabled():
            return
        with self._lock:
            if any(w.message_id == message_id for w in self._queue):
                return
            self._queue.append(Waiting(message_id, ts, frozenset(why), self._clock()))
            del self._queue[:-QUEUE_MAX]
        self._wake.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ai correct", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _next(self) -> Waiting | None:
        with self._lock:
            now = self._clock()
            for n, waiting in enumerate(self._queue):
                if now - waiting.since >= DELAY_S:
                    return self._queue.pop(n)
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            waiting = self._next()
            if waiting is None:
                self._wake.wait(DELAY_S / 2)
                self._wake.clear()
                continue
            try:
                self.handle(waiting)
            except Exception:  # one odd line must not end the corrections for the evening
                log.exception("correct: line %s", waiting.message_id)

    def handle(self, waiting: Waiting) -> None:
        """One line: ask, compare, store. Public for the tests (no thread there)."""
        message = self._store.message(waiting.message_id)
        if message is None or message.edited_at is not None or message.ai_corrected_at:
            return  # gone, fixed by hand meanwhile, or done
        path = self._picture(message.id, message.ts)
        picture = images.read(path) if path is not None else None
        if picture is None:
            return
        ok, png = cv2.imencode(".png", picture)
        if not ok:
            return
        for trigger in waiting.why:
            self.counts[trigger] = self.counts.get(trigger, 0) + 1
        got = self._corrector.correct(png.tobytes())
        if got.row is None:
            log.info("correct: line %s not corrected (%s)", message.id, got.error)
            return
        box = Region(0, 0, picture.shape[1], picture.shape[0])
        line = parse_chat([OcrLine(got.row, 1.0, box)])[0]
        speaker = line.speaker if line.speaker and message.speaker_raw else message.speaker_raw
        text = icons.name(line.text, picture) if line.text.strip() else message.text
        if (speaker, glyphs.unnamed(text)) == (message.speaker_raw, glyphs.unnamed(message.text)):
            return  # the AI read what OCR read: nothing to change
        if not self._store.ai_correct_message(message.id, text=text, speaker_raw=speaker,
                                              has_glyphs=glyphs.has_glyphs(text),
                                              ts=time.time()):  # fmt: skip
            return  # fixed by hand while the AI was reading
        if speaker != message.speaker_raw and message.channel != "system":
            self._store.set_message_player(message.id, self._relink(speaker, message.ts))
        self.corrected += 1
        log.info("correct: line %s corrected by %s (%s)", message.id, got.model,
                 ", ".join(sorted(waiting.why)))  # fmt: skip
        self._label({"id": message.id, "ts": message.ts, "speaker": speaker, "text": text,
                     "ocr_speaker": message.speaker_raw, "ocr_text": message.text,
                     "model": got.model, "source": "ai"})  # fmt: skip
        self._saved(message.id)
