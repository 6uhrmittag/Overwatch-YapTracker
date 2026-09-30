"""Things the running app shares between its parts."""

from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

PAUSE_HOTKEY = "Ctrl+Alt+P"

pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
changes: ChangeDetector | None = None  # frames that would go to OCR (#17)
window_size: tuple[int, int] | None = None  # of the captured Overwatch window, for #84's hint
store: Store | None = None  # the database, open while the app runs (#15)
