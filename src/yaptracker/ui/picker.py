"""Picking chat lines for a yap snap (#64, #155): in a match transcript and in search results.

Click a line to add it or take it out again; shift-click takes every line between it and the
one clicked before, up to the 20 a snap can hold.
"""

from collections.abc import Callable

from nicegui import ui

from yaptracker.snaps import MAX_LINES
from yaptracker.ui.components import button


class LinePicker:
    def __init__(self, on_make: Callable[[list], None]) -> None:
        self._on_make = on_make
        self.on = False
        self.picked: dict[int, object] = {}  # message id -> message
        self._rows: dict[int, tuple[object, ui.element]] = {}  # in display order
        self._last: int | None = None

    def start_button(self) -> ui.element:
        """The "Make a yap snap" button, for the header."""
        self._start = button("Make a yap snap", lambda: self.pick(True), "quiet").mark("snap-start")
        return self._start

    def bar(self) -> ui.element:
        """The "N of 20 picked" bar with Cancel and Make the snap, hidden until picking."""
        with ui.element("div").classes("yt-snap-bar yt-hidden").mark("snap-bar") as self._bar:
            self._text = ui.label().classes("yt-grow")
            button("Cancel", lambda: self.pick(False), "quiet").mark("snap-cancel")
            self._make = button("Make the snap", lambda: self.make(), "primary").mark("snap-make")
        return self._bar

    def clear_rows(self) -> None:
        """The list is drawn again (a new search): picked lines stay picked."""
        self._rows = {}

    def add(self, message, element: ui.element) -> None:
        self._rows[message.id] = (message, element)
        if message.id in self.picked:
            element.classes(add="yt-line--picked")

    def pick(self, on: bool) -> None:
        self.on, self._last = on, None
        for _, element in self._rows.values():
            element.classes(remove="yt-line--picked")
        self.picked.clear()
        self._bar.classes(**{"remove" if on else "add": "yt-hidden"})
        self._start.classes(**{"add" if on else "remove": "yt-hidden"})
        self._show_count()

    def clicked(self, message, shift: bool = False) -> bool:
        """A click on a line; False if not picking (the caller shows the line's picture)."""
        if not self.on:
            return False
        ids = list(self._rows)
        if shift and self._last in self._rows and message.id in self._rows:
            a, b = sorted((ids.index(self._last), ids.index(message.id)))
            for mid in ids[a : b + 1]:
                if len(self.picked) < MAX_LINES:
                    self._take(mid)
        elif message.id in self.picked:
            del self.picked[message.id]
            self._rows[message.id][1].classes(remove="yt-line--picked")
        elif len(self.picked) < MAX_LINES:
            self._take(message.id)
        self._last = message.id
        self._show_count()
        return True

    def make(self) -> None:
        self._on_make(sorted(self.picked.values(), key=lambda m: (m.ts, m.id)))

    def _take(self, message_id: int) -> None:
        message, element = self._rows[message_id]
        self.picked[message_id] = message
        element.classes(add="yt-line--picked")

    def _show_count(self) -> None:
        n = len(self.picked)
        self._text.set_text(
            f"{n} of {MAX_LINES} picked: click the lines you want on the snap, shift-click for "
            "a whole stretch"
        )
        self._make.props(**{"add" if n == 0 else "remove": "disabled"})
