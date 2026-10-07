"""Read after the match (#332 a, #335): during such a match no chat is read. The chat frames that
changed are kept in memory and read once the game is idle again, with their real timestamps,
into the match they were seen in.

At most one frame per read gap is kept (the newest wins, as in live reading: a line stays ~9 s
on screen). Above the memory cap, the frame whose neighbours are closest together goes first:
it's the one whose lines the others most likely show too. Neighbours only count within one
match, and a match's first and last frame always stay (#356): with back-to-back matches waiting
together under the one cap, both stay readable.

Quitting normally with frames unread writes them to data/unread/ as they are (raw, nothing to
encode), and the next start reads them first (#349). Nothing is written to disk during a match
but a tiny note: a crash loses the frames, and the note's time span becomes a gap record
('deferred_lost', #75) at the next start: never a silent hole.
"""

import json
import logging
import shutil
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CAP_BYTES = 150 * 1024 * 1024  # ~200 chat boxes at 1440p, ~90 at 4K
NOTE_EVERY_S = 10.0  # how often the waiting span is written down (a crash loses at most this)
KEEP_S = 2 * 24 * 3600  # frames saved at quit older than this aren't read any more (#349)
INDEX = "index.json"  # written last: a folder without it was cut off mid-write


@dataclass
class Kept:
    since: float  # when its read gap began; a newer frame within the gap replaces it
    ts: float
    image: np.ndarray
    match_id: int | None
    mode: str  # how it's read: 'after' frames with the best quality, others as they were seen


class LaterFrames:
    def __init__(
        self,
        gap_s: Callable[[], float],
        note: Path | None,
        cap_bytes: int = CAP_BYTES,
        unread: Path | None = None,
    ) -> None:
        self._gap, self._note, self._cap, self._unread = gap_s, note, cap_bytes, unread
        self._lock = threading.Lock()
        self._frames: list[Kept] = []
        self._bytes = 0
        self._noted_at: float | None = None
        self.kept = 0  # since the last take_counts()
        self.dropped: Counter[int | None] = Counter()  # match -> frames dropped for the cap

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
            while self._bytes > self._cap and self._drop_one():
                pass
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

    def close(self) -> tuple[float, float] | None:
        """Quitting (#349): unread frames go to disk for the next start. Returns the span of
        frames that couldn't be kept (for a gap record), None if nothing was lost."""
        if self._unread is None:
            return self.discard()
        with self._lock:
            frames, self._frames, self._bytes, self._noted_at = self._frames, [], 0, None
        if not frames:
            self._forget_note()
            return None
        try:
            shutil.rmtree(self._unread, ignore_errors=True)
            self._unread.mkdir(parents=True)
            index = []
            for n, kept in enumerate(frames):
                np.save(self._unread / f"{n:04d}.npy", kept.image, allow_pickle=False)
                index.append({"file": f"{n:04d}.npy", "since": kept.since, "ts": kept.ts,
                              "match": kept.match_id, "mode": kept.mode})  # fmt: skip
            (self._unread / INDEX).write_text(json.dumps(index), encoding="utf-8")
        except OSError as error:
            log.warning("can't keep the unread chat frames for the next start: %s", error)
            shutil.rmtree(self._unread, ignore_errors=True)
            self._forget_note()
            return frames[0].ts, frames[-1].ts
        self._forget_note()
        log.info("kept %d unread chat frames for the next start", len(frames))
        return None

    def restore(self, now: float | None = None) -> tuple[float, float] | None:
        """At start: frames kept by the last quit wait to be read again, first of all. Older
        than KEEP_S: dropped, and their span returned for a gap record. The folder goes."""
        if self._unread is None or not self._unread.exists():
            return None
        now = time.time() if now is None else now
        try:
            index = json.loads((self._unread / INDEX).read_text(encoding="utf-8"))
            frames = [Kept(e["since"], e["ts"], np.load(self._unread / e["file"]), e["match"],
                           e["mode"]) for e in index]  # fmt: skip
        except (OSError, ValueError, KeyError, TypeError) as error:
            log.warning("the chat frames kept at the last quit can't be read: %s", error)
            frames = []
        finally:
            shutil.rmtree(self._unread, ignore_errors=True)
        if not frames:
            return None
        span = (frames[0].ts, frames[-1].ts)
        if now - span[1] > KEEP_S:
            log.warning("chat frames kept at the last quit are too old to read: %d dropped",
                        len(frames))  # fmt: skip
            return span
        with self._lock:
            self._frames = frames + self._frames
            self._bytes += sum(k.image.nbytes for k in frames)
            self._noted_at = now
        self._write_note(*span)  # a crash while reading them: still a gap, not a hole
        log.info("%d chat frames kept at the last quit wait to be read", len(frames))
        return None

    def take_counts(self) -> tuple[int, Counter]:
        """(frames kept, {match: frames dropped for the cap}) since the last call."""
        with self._lock:
            counts = self.kept, self.dropped
            self.kept, self.dropped = 0, Counter()
            return counts

    def _drop_one(self) -> bool:
        """Drop the frame whose neighbours in its own match are closest: the least time goes
        unseen. A match's first and last frame stay. False if nothing can go."""
        frames = self._frames
        inner = [
            i
            for i in range(1, len(frames) - 1)
            if frames[i - 1].match_id == frames[i].match_id == frames[i + 1].match_id
        ]
        if not inner:
            return False
        i = min(inner, key=lambda i: frames[i + 1].ts - frames[i - 1].ts)
        match_id = frames[i].match_id
        self._bytes -= frames.pop(i).image.nbytes
        if match_id not in self.dropped:
            log.warning("memory cap: dropping chat frames of match %s that its neighbours cover",
                        match_id)  # fmt: skip
        self.dropped[match_id] += 1
        return True

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
