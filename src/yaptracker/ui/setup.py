"""First start (#76): 1 Find Overwatch -> 2 Draw the chat box -> 3 Who are you? -> go play.

Skippable at any point; nothing breaks without it (the usual chat spot and no names are the
defaults), and Live reminds once. Capture runs the whole time, so setup never costs a match.
"""

import sys
from collections.abc import Callable

from nicegui import ui

from yaptracker import autostart, config, runtime
from yaptracker.capture.black import SAY as BLACK_SAY
from yaptracker.ui.calibrate import calibrate
from yaptracker.ui.components import button, set_button_label, stepper, switch
from yaptracker.ui.crew import crew_card

STEPS = ("Find Overwatch", "Draw the chat box", "Who are you?")


def startup_card() -> None:
    """Start with Windows (#45): in Settings and in the last setup step."""
    with ui.element("section").classes("yt-card").mark("startup"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Startup").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            supported = autostart.supported()
            switch(
                "Start with Windows",
                autostart.enabled(),
                autostart.set_enabled,
                disabled=not supported,
            ).mark("autostart")
            ui.label(
                "Waits quietly in the taskbar until Overwatch starts, so no evening "
                "is lost because YapTracker wasn't open."
                if supported
                else "Only in the installed app (tools/update.ps1)."
            ).classes("yt-hint")


def _windowed() -> bool:
    """Overwatch runs in a window with a title bar: the chat box would sit off by its height."""
    watcher = runtime.watcher
    if sys.platform != "win32" or watcher is None or watcher.window is None:
        return False
    from yaptracker.capture.window import has_title_bar

    return has_title_bar(watcher.window)


def _fullscreen() -> bool:
    """Exclusive Fullscreen: Windows says so, or the picture stayed black (#217)."""
    if runtime.black is not None and runtime.black.black:
        return True
    watcher = runtime.watcher
    if sys.platform != "win32" or watcher is None or watcher.window is None:
        return False
    from yaptracker.capture.window import exclusive_fullscreen

    return exclusive_fullscreen(watcher.window)


def _overwatch_status() -> tuple[bool, str, str]:
    """(found, what I see, what to do) for step 1."""
    watcher, size = runtime.watcher, runtime.window_size
    if watcher is None or watcher.state != "capturing" or size is None:
        return (
            False,
            "Start Overwatch, I'll wait right here.",
            "Already running? Bring it up once, so I can find its window.",
        )
    seen = f"Found Overwatch at {size[0]}\u00d7{size[1]}."
    if _fullscreen():  # never "perfect" then (#217)
        return True, seen, BLACK_SAY
    if _windowed():
        return (
            True,
            seen,
            "It runs in a window with a title bar. Options \u2192 Video \u2192 Display mode: "
            "Borderless Windowed, then I see exactly what you see.",
        )
    return True, seen, "Borderless windowed, perfect. That's all I need."


def setup_wizard(on_done: Callable[[], None], start: int = 1) -> None:
    body = ui.element("div").classes("yt-view").mark("setup")

    def go(step: int) -> None:
        body.clear()
        with body:
            (find_overwatch, draw_box, who_are_you)[step - 1]()

    def finish(state: str) -> None:
        config.save_setup_state(state)
        on_done()

    def header(title: str, subtitle: str, step: int) -> None:
        with ui.element("header").classes("yt-header"):
            with ui.element("div"):
                ui.label(title).classes("yt-h1")
                ui.label(subtitle).classes("yt-subtitle")
            ui.element("div").classes("yt-grow")
            stepper(STEPS, step)

    def find_overwatch() -> None:
        header("Let's find Overwatch", "One-time setup. Takes about 30 seconds, promise.", 1)
        with ui.element("section").classes("yt-card").mark("find"):
            with ui.element("div").classes("yt-card-body"):
                seen = ui.label().classes("yt-h2")
                todo = ui.label().classes("yt-text-soft")
        with ui.element("div").classes("yt-actions"):
            button("Skip setup", lambda: finish("skipped"), "quiet").mark("skip-setup")
            # Without the game, step 2 still works with a screenshot file.
            button("Next \u2192", lambda: go(2), "primary").mark("setup-next")

        def refresh() -> None:
            _, what, hint = _overwatch_status()
            seen.set_text(what)
            todo.set_text(hint)

        ui.timer(1.0, refresh)
        refresh()

    def draw_box() -> None:
        calibrate(on_done=lambda saved: go(3 if saved else 1), steps=lambda: stepper(STEPS, 2))

    def who_are_you() -> None:
        header("Who are you?", "So your own yaps show as you, and your crew never gets a "
               "\u201cLook who's back!\u201d.", 3)  # fmt: skip
        crew_card()
        startup_card()
        with ui.element("div").classes("yt-banner yt-hidden").mark("no-name") as nudge:
            ui.label("Add at least your own name, otherwise I'll greet you as a stranger.").classes(
                "yt-grow"
            )
        with ui.element("div").classes("yt-actions"):
            button("Back", lambda: go(2), "quiet")
            done = button("All set - go play!", lambda: all_set(), "primary").mark("setup-done")

        def all_set() -> None:
            """Without your own name, your own lines would get a "Look who's back!" (#168)."""
            if config.identity().me or "yt-hidden" not in nudge.classes:
                finish("done")
                return
            nudge.classes(remove="yt-hidden")
            set_button_label(done, "Go play without my name")

    go(start)
