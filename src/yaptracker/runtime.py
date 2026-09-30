"""Things the running app shares between its parts."""

from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.pause import Pause

PAUSE_HOTKEY = "Ctrl+Alt+P"

pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
changes: ChangeDetector | None = None  # frames that would go to OCR (#17)
