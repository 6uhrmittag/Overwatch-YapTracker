"""Read again, best quality (#333): a match's lines, or one line, read again from their saved
pictures (#120) with the best engine, e.g. a match read light (#331) or older garbled lines.

A new reading replaces a line only when it's better: more confident, or more letters once
umlauts and punctuation are folded away. Lines fixed by hand (#227) are never touched. It runs
on a low-priority thread of its own and only while no match runs; a line YapTracker never saw
has no picture, so it can't be found this way (the tidy-up of #336 keeps whole frames for that).
"""

import logging
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from yaptracker import glyphs, priority
from yaptracker.dedup import YAP_KINDS
from yaptracker.identity import Identity
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import ChatLine, parse

log = logging.getLogger(__name__)
WAIT_S = 2.0  # a match runs, or nothing to do: look again this often


def letters(*parts: str | None) -> int:
    """Letters and digits, umlauts and accents folded to their base letter."""
    plain = unicodedata.normalize("NFKD", " ".join(p for p in parts if p))
    return sum(ch.isalnum() for ch in plain if not unicodedata.combining(ch))


def better(message, line: ChatLine) -> bool:
    if (line.speaker, line.text, line.hero) == (message.speaker_raw, message.text, message.hero):
        return False
    return line.confidence > (message.ocr_confidence or 0.0) or letters(
        line.speaker, line.text
    ) > letters(message.speaker_raw, message.text)


@dataclass
class Job:
    """One "read again": a match's lines or one line, and how far it got."""

    match_id: int | None
    ids: list[int]
    done: int = 0
    better: list[int] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.done >= len(self.ids)


class ReadAgain:
    def __init__(
        self,
        store,
        pictures,
        read: Callable[[np.ndarray], list[OcrLine]],
        idle: Callable[[], bool],
        identity: Callable[[], Identity] = Identity,
        link: Callable[[str | None, float, float], int | None] = lambda name, ts, conf: None,
    ) -> None:
        self._store, self._pictures, self._read, self._idle = store, pictures, read, idle
        self._identity, self._link = identity, link
        self._lock = threading.Lock()
        self._jobs: list[Job] = []
        self._wake = threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def match(self, match_id: int) -> Job:
        """Every line of the match that has a picture and wasn't fixed by hand."""
        ids = [m.id for m in self._store.messages(match_id) if self._readable(m)]
        return self._add(Job(match_id, ids))

    def line(self, message_id: int) -> Job:
        message = self._store.message(message_id)
        ok = message is not None and self._readable(message)
        return self._add(Job(message.match_id if message else None, [message_id] if ok else []))

    def job(self, match_id: int | None) -> Job | None:
        """The newest job of that match, finished or not (for its progress line)."""
        with self._lock:
            return next((j for j in reversed(self._jobs) if j.match_id == match_id), None)

    def run_once(self) -> bool:
        """Reads one line of the oldest unfinished job, if no match runs. (Tests call it.)"""
        with self._lock:
            job = next((j for j in self._jobs if not j.finished), None)
        if job is None or not self._idle():
            return False
        message_id = job.ids[job.done]
        try:
            improved = self._again(message_id)
        except Exception:
            log.exception("reading line %d again failed", message_id)
            improved = False
        with self._lock:
            job.done += 1
            if improved:
                job.better.append(message_id)
        if job.finished:
            log.info("read %d line(s) again (match %s): %d better", len(job.ids), job.match_id,
                     len(job.better))  # fmt: skip
        return True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="read again", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        priority.lower_this_thread()  # the game first, as the chat reader (#187)
        while not self._stopping:
            if not self.run_once():
                self._wake.wait(WAIT_S)
                self._wake.clear()

    def _add(self, job: Job) -> Job:
        with self._lock:
            self._jobs = [j for j in self._jobs if not j.finished] + [job]
        self._wake.set()
        return job

    def _readable(self, message) -> bool:
        return message.edited_at is None and self._pictures.path(message.id, message.ts).exists()

    def _again(self, message_id: int) -> bool:
        message = self._store.message(message_id)
        if message is None or message.edited_at is not None:  # fixed by hand in the meantime
            return False
        image = cv2.imread(str(self._pictures.path(message.id, message.ts)))
        if image is None:
            return False
        lines = parse(glyphs.mark(image, self._read(image)))
        lines = [line for line in self._identity().apply(lines) if line.kind in YAP_KINDS]
        if len(lines) != 1 or not better(message, lines[0]):
            return False  # nothing, or more than one line: can't tell which is this one
        line = lines[0]
        system = message.channel == "system"
        player = message.player_id
        if not system and line.speaker != message.speaker_raw:
            player = self._link(line.speaker, message.ts, line.confidence)
        self._store.update_message(
            message.id, channel=message.channel, text=line.text, speaker_raw=line.speaker,
            hero=line.hero, ocr_confidence=line.confidence,
            flagged="overwatch" if line.flagged else message.flagged, role=line.role,
            has_glyphs=glyphs.has_glyphs(line.text), player_id=None if system else player,
        )  # fmt: skip
        return True
