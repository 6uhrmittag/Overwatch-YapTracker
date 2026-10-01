"""Things the running app shares between its parts."""

from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.debug import DebugSamples
from yaptracker.familiar import FamiliarFaces
from yaptracker.lines import LinePictures
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.backups import DailyBackup
from yaptracker.store.repo import Store

PAUSE_HOTKEY = "Ctrl+Alt+P"
NEW_MATCH_HOTKEY = "Ctrl+Alt+M"  # manual override only; matches split themselves (#21)
LOOKUP_HOTKEY = "Ctrl+Alt+F"  # "Who's that?": YapTracker to the front, search focused (#27)
SAVE_HOTKEY = "Ctrl+Alt+S"  # optional: keep the last 20 s of chat as a debug sample (#110)

pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
changes: ChangeDetector | None = None  # frames that would go to OCR (#17)
window_size: tuple[int, int] | None = None  # of the captured Overwatch window, for #84's hint
store: Store | None = None  # the database, open while the app runs (#15)
matches: MatchTracker | None = None  # sessions and matches (#21), with the store
health: CaptureHealth | None = None  # gap records (#75), with the store
debug: DebugSamples | None = None  # the hard moments, kept as test material (#63)
reader: ChatReader | None = None  # live chat into the database (#108), with the store
backups: DailyBackup | None = None  # one copy of the database a day (#125), with the store
pictures: LinePictures | None = None  # the picture of every chat line (#120)
familiar: FamiliarFaces | None = None  # "Look who's back!" cards (#26), with the store
lookup_requested = 0.0  # monotonic time of the last Ctrl+Alt+F; the UI focuses the search box
