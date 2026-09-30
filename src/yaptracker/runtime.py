"""Things the running app shares between its parts."""

from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.pause import Pause

PAUSE_HOTKEY = "Ctrl+Alt+P"

pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
