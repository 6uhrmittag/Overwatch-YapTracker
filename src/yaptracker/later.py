"""Read after the match (#332 a, #335): during such a match no chat is read. The chat frames that
changed are kept in memory and read once the game is idle again, with their real timestamps,
into the match they were seen in.

At most one frame per read gap is kept (the newest wins, as in live reading: a line stays ~9 s
on screen). Above the memory cap, the frame whose neighbours are closest together goes first:
it's the one whose lines the others most likely show too.

A crash or quitting loses the frames. Their time span is noted in a small file while frames
wait, so the next start turns it into a gap record ('deferred_lost', #75): never a silent hole.
"""

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CAP_BYTES = 150 * 1024 * 1024  # ~200 chat boxes at 1440p, ~90 at 4K
NOTE_EVERY_S = 10.0  # how often the waiting span is written down (a crash loses at most this)


@dataclass
class Kept:
    since: float  # when its read gap began; a newer frame within the gap replaces it
    ts: float
    image: np.ndarray
    match_id: int | None
    mode: str  # how it's read: 'after' frames with the best quality, others as they were seen


class LaterFrames:
    def __init__(
        self, gap_s: Callable[[], float], note: Path | None, cap_bytes: int = CAP_BYTES
    ) -> None:
        self._gap, self._note, self._cap = gap_s, note, cap_bytes
        self._lock = threading.Lock()
        self._frames: list[Kept] = []
        self._bytes = 0
        self._noted_at: float | None = None
        self.kept = self.dropped = 0  # since the last take_counts()

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    def add(self, ts: float, image: np.ndarray, match_id: int | None, mode: str) -> None:
        """From the capture thread: a changed chat frame. Never reads, never blocks for long."""
        with self._lock:
            last = self._frames[-1] if self._frames else None
            same = last is not None and (last.match_id, last.mode) == (match_id, mode)
            if same and ts - last.since < self._gap():
                self._bytes += image.nbytes - last.image.nbytes
                last.ts, last.image = ts, image
            else:
                self._frames.append(Kept(ts, ts, image, match_id, mode))
                self._bytes += image.nbytes
                self.kept += 1
            while self._bytes > self._cap and len(self._frames) > 2:
                self._drop_one()
            first, newest = self._frames[0].ts, self._frames[-1].ts
            if self._noted_at is None or ts - self._noted_at >= NOTE_EVERY_S:
                self._noted_at = ts
                self._write_note(first, newest)

    def pop(self) -> Kept | None:
        """The oldest frame, to be read now. The note goes once the last one is out."""
        with self._lock:
            if not self._frames:
                return None
            frame = self._frames.pop(0)
            self._bytes -= frame.image.nbytes
            if not self._frames:
                self._noted_at = None
                self._forget_note()
            return frame

    def discard(self) -> tuple[float, float] | None:
        """Quitting with frames still unread: they're gone; returns their span for the gap."""
        with self._lock:
            frames, self._frames, self._bytes, self._noted_at = self._frames, [], 0, None
            self._forget_note()
            return (frames[0].ts, frames[-1].ts) if frames else None

    def take_counts(self) -> tuple[int, int]:
        """(frames kept, frames dropped for the cap) since the last call."""
        with self._lock:
            counts = self.kept, self.dropped
            self.kept = self.dropped = 0
            return counts

    def _drop_one(self) -> None:
        """Drop the inner frame whose neighbours are closest: the least time goes unseen."""
        frames = self._frames
        i = min(range(1, len(frames) - 1), key=lambda i: frames[i + 1].ts - frames[i - 1].ts)
        self._bytes -= frames.pop(i).image.nbytes
        self.dropped += 1

    def _forget_note(self) -> None:
        if self._note is not None:
            self._note.unlink(missing_ok=True)

    def _write_note(self, first: float, last: float) -> None:
        if self._note is None:
            return
        try:
            self._note.parent.mkdir(parents=True, exist_ok=True)
            self._note.write_text(json.dumps({"first": first, "last": last}), encoding="utf-8")
        except OSError as error:  # only the crash note: reading later still works
            log.warning("can't note the frames waiting to be read: %s", error)


def lost_span(note: Path) -> tuple[float, float] | None:
    """The span of frames a crash or quit left unread, once; the note is gone afterwards."""
    if not note.exists():
        return None
    try:
        data = json.loads(note.read_text(encoding="utf-8"))
        return float(data["first"]), float(data["last"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("the note of unread frames is broken (%s): ignored", error)
        return None
    finally:
        note.unlink(missing_ok=True)
