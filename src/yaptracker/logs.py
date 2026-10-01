"""The app log (#98): data\\logs\\yaptracker.log, at most 5 files of 1 MB each.

The windowed exe has no console, so whatever goes to stdout/stderr (prints, uncaught
tracebacks, warnings) is routed into the same log. Only the main process writes it: the native
window's child process gets its own small window.log, new at every start, because Windows
can't rotate a file that another process holds open.
"""

import io
import logging
import multiprocessing.spawn
import os
import sys
from logging.handlers import RotatingFileHandler

from yaptracker import paths

MAX_BYTES = 1_000_000
BACKUPS = 4  # yaptracker.log + .1 ... .4 = 5 files
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class ToLog(io.TextIOBase):
    """Stands in for the missing console: every complete line goes to a logger."""

    encoding = "utf-8"

    def __init__(self, logger: logging.Logger, level: int) -> None:
        super().__init__()
        self._logger, self._level = logger, level
        self._partial = ""
        self._busy = False

    def write(self, text: str) -> int:
        if self._busy:  # the log itself failed and reports that on stderr: don't loop
            return len(text)
        self._busy = True
        try:
            *lines, self._partial = (self._partial + text).split("\n")
            for line in lines:
                if line.strip():
                    self._logger.log(self._level, line.rstrip())
        finally:
            self._busy = False
        return len(text)

    def writable(self) -> bool:
        return True


def setup(argv: list[str] | None = None) -> None:
    folder = paths.log_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    if multiprocessing.spawn.is_forking(sys.argv if argv is None else argv):
        if sys.stdout is None or sys.stderr is None:  # the native window's process, see above
            stream = open(folder / "window.log", "w", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
            sys.stdout = sys.stdout or stream
            sys.stderr = sys.stderr or stream
        return
    handler = RotatingFileHandler(
        paths.log_file(), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    if sys.stderr is not None:  # a console (--dev, python -m): warnings show there too
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(console)
    if sys.stdout is None:
        sys.stdout = ToLog(logging.getLogger("stdout"), logging.INFO)
    if sys.stderr is None:
        sys.stderr = ToLog(logging.getLogger("stderr"), logging.WARNING)


def folder_opens() -> bool:
    """Open logs needs Explorer, so Windows only."""
    return sys.platform == "win32"


def open_folder() -> None:
    os.startfile(paths.log_file().parent)  # type: ignore[attr-defined]  # Windows only
