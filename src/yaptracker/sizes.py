"""How big a folder is, without walking it every time (#387): Settings asked on every open and
walked ~10,000 files on Marv's PC (1-2 s). Each store counts its folder once at start, in the
background, and then keeps the total itself: it adds what it writes and drops what it deletes.
"""

import threading
from collections.abc import Callable, Iterable
from pathlib import Path


class FolderSizes:
    """Sizes of a folder's units (a file, or a sample folder), and their total."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sizes: dict[Path, int] = {}
        self._total = 0
        self.ready = threading.Event()  # counted: until then the total is unknown

    def counted(self, found: Iterable[tuple[Path, int]]) -> None:
        """The walk at start. What was written meanwhile is newer than what the walk saw."""
        with self._lock:
            for unit, size in found:
                self._sizes.setdefault(unit, size)
            self._total = sum(self._sizes.values())
        self.ready.set()

    def set(self, unit: Path, size: int) -> None:
        """A unit was written (or written over)."""
        with self._lock:
            self._total += size - self._sizes.get(unit, 0)
            self._sizes[unit] = size

    def drop(self, folder: Path) -> int:
        """`folder` was deleted: it and every unit in it. The bytes that went."""
        with self._lock:
            gone = [u for u in self._sizes if u == folder or folder in u.parents]
            freed = sum(self._sizes.pop(u) for u in gone)
            self._total -= freed
            return freed

    def total(self) -> int | None:
        """The folder's size, or None while it's still being counted."""
        with self._lock:
            return self._total if self.ready.is_set() else None

    def snapshot(self) -> dict[Path, int]:
        with self._lock:
            return dict(self._sizes)

    def count(self, walk: Callable[[], Iterable[tuple[Path, int]]], then: Callable[[], None],
              background: bool = True) -> None:  # fmt: skip
        """Walk the folder once (off the calling thread unless `background` is off), then run
        `then` (the clean-up)."""

        def run() -> None:
            self.counted(list(walk()))
            then()

        if background:
            threading.Thread(target=run, name="folder sizes", daemon=True).start()
        else:
            run()
