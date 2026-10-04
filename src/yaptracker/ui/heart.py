"""Heart a match to find it again (#282): one click in Live's chat card or a match in Sessions,
with Saved + Undo like the quick verdicts (#220). An icon, never an emoji (docs/ui.md)."""

import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui import icons

LOVE = "Love this match: find it again in Sessions"
LOVED = "Loved: click to take it back"


class Heart:
    """A heart button for one match at a time; `show(match_id)` points it at another."""

    def __init__(self, title: Callable[[int], str] = lambda match_id: "this match",
                 on_change: Callable[[], None] = lambda: None) -> None:  # fmt: skip
        self._title, self._on_change = title, on_change
        self.match_id: int | None = None
        with ui.element("button").classes("yt-heart").mark("heart") as self.button:
            ui.html(icons.HEART, sanitize=False)
        self.button.props('type="button"')
        self.button.on("click", lambda: self.toggle())
        self.show(None)

    def show(self, match_id: int | None) -> None:
        """Follow a match (None: hidden, nothing to love yet)."""
        self.match_id = match_id
        loved = match_id is not None and runtime.store is not None and runtime.store.loved(match_id)
        self.button.classes(**{"remove" if match_id is not None else "add": "yt-hidden"})
        self.button.classes(**{"add" if loved else "remove": "is-on"})
        self.button.props(f'title="{LOVED if loved else LOVE}" aria-pressed="{str(loved).lower()}"')

    def toggle(self) -> None:
        match_id, store = self.match_id, runtime.store
        if match_id is None or store is None:
            return
        before = store.loved(match_id)
        bar = getattr(ui.context.client, "yt_undo", None)
        store.set_loved(match_id, None if before else time.time())
        self.show(match_id)
        self._on_change()
        if bar is not None:

            def undo() -> None:
                store.set_loved(match_id, time.time() if before else None)
                self.show(self.match_id)
                self._on_change()

            title = self._title(match_id)
            bar.show(f"Not loved: {title}" if before else f"Loved: {title}", undo)
