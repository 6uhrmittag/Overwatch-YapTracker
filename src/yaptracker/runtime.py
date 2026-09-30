"""Things the running app shares between its parts. None in tests and before startup."""

from yaptracker.capture.watcher import CaptureWatcher

watcher: CaptureWatcher | None = None
