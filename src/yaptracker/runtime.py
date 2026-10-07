"""Things the running app shares between its parts."""

from collections.abc import Callable

from yaptracker import config
from yaptracker.capture.black import BlackPicture, ScreenFallback
from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.health import CaptureHealth
from yaptracker.capture.watcher import CaptureWatcher
from yaptracker.debug import DebugSamples
from yaptracker.familiar import FamiliarFaces
from yaptracker.lines import LinePictures
from yaptracker.matches import MatchTracker
from yaptracker.pause import Pause
from yaptracker.players import PlayerMatcher
from yaptracker.read_again import ReadAgain
from yaptracker.reader import ChatReader
from yaptracker.reading_mode import ReadingMode
from yaptracker.store.backups import DailyBackup
from yaptracker.store.repo import Store


def ocr_scale() -> float:
    """How much OCR enlarges a crop of the captured window (#169): 2x up to 1440p, less above."""
    from yaptracker.ocr.engine import upscale_for

    return upscale_for(window_size[1] if window_size else None)


def keycap(action: str) -> str:
    """The hotkey of an action as a keycap label, e.g. "Ctrl Alt P" (changeable, #32);
    "" when it's not set, so no keycap is shown (#328)."""
    return config.hotkeys()[action].replace("+", " ")


pause = Pause()
watcher: CaptureWatcher | None = None  # None in tests and before startup
black: BlackPicture | None = None  # Windows sends a black picture (#217)
screen: ScreenFallback | None = None  # the window stayed black: read the screen (#236)
changes: ChangeDetector | None = None  # frames that would go to OCR (#17)
window_size: tuple[int, int] | None = None  # of the captured Overwatch window, for #84's hint
store: Store | None = None  # the database, open while the app runs (#15)
matches: MatchTracker | None = None  # sessions and matches (#21), with the store
health: CaptureHealth | None = None  # gap records (#75), with the store
debug: DebugSamples | None = None  # the hard moments, kept as test material (#63)
reader: ChatReader | None = None  # live chat into the database (#108), with the store
reading: ReadingMode | None = None  # which reader reads during which match (#331)
read_again: ReadAgain | None = None  # "Read again, best quality" from line pictures (#333)
backups: DailyBackup | None = None  # one copy of the database a day (#125), with the store
pictures: LinePictures | None = None  # the picture of every chat line (#120)
players: PlayerMatcher | None = None  # speakers -> players (#23); reloaded after a merge
familiar: FamiliarFaces | None = None  # "Look who's back!" cards (#26), with the store
hotkeys = None  # the HotkeyListener (Windows app only); .failed = keys another app owns
bind_hotkeys: Callable[[bool], None] | None = None  # (re)register them; None in --dev and tests
data_too_new: str | None = None  # the database is from a newer YapTracker (#352)
lookup_requested = 0.0  # monotonic time of the last Ctrl+Alt+F; the UI focuses the search box
