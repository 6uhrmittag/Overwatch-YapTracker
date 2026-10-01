"""Things the running app shares between its parts."""

from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.debug import DebugSamples
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.store.repo import Store

PAUSE_HOTKEY = "Ctrl+Alt+P"
NEW_MATCH_HOTKEY = "Ctrl+Alt+M"  # manual override only; matches split themselves (#21)

pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
changes: ChangeDetector | None = None  # frames that would go to OCR (#17)
window_size: tuple[int, int] | None = None  # of the captured Overwatch window, for #84's hint
store: Store | None = None  # the database, open while the app runs (#15)
matches: MatchTracker | None = None  # sessions and matches (#21), with the store
health: CaptureHealth | None = None  # gap records (#75), with the store
debug: DebugSamples | None = None  # the hard moments, kept as test material (#63)
