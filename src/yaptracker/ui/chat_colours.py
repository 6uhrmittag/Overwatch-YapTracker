"""Settings -> Chat colours (#401): one colour per channel, so lines look like your own chat box
in Overwatch. Each row: a colour picker with its hex, a line in that colour, and a warning when
it's hard to read on the dark background. Applied at once, no restart."""

from nicegui import ui

from yaptracker import chat_colours
from yaptracker.chat_colours import NAMES
from yaptracker.ui.components import button, saved_chip

HINT = "Match the colours you use in Overwatch, so lines look the same here."
HARD_TO_READ = "Hard to read on the dark background."
_SAMPLES = {  # (name, text) of the preview line; system lines have no name
    "team": ("Someone", "on my way"),
    "match": ("Someone", "gg wp"),
    "group": ("Someone", "one more?"),
    "system": ("", "[Someone] started playing Overwatch."),
    "chat": ("Someone", "glhf"),
}


def chat_colours_card() -> None:
    with ui.element("section").classes("yt-card").mark("chat-colours"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Chat colours").classes("yt-h2")
            status = ui.element("div")
            ui.element("div").classes("yt-grow")
            button("Reset to Overwatch defaults", lambda: reset(), "quiet").mark("colours-reset")
        with ui.element("div").classes("yt-card-body"):
            ui.label(HINT).classes("yt-hint")
            rows = ui.element("div").classes("yt-colour-rows")
    warnings: dict[str, ui.label] = {}

    def show(colours: dict[str, str]) -> None:
        rows.clear()
        with rows:
            for key, colour in colours.items():
                with ui.element("div").classes("yt-colour-row"):
                    ui.color_input(
                        NAMES[key], value=colour, on_change=lambda e, k=key: pick(k, e.value)
                    ).props("dense").classes("yt-colour-pick").mark(f"colour-{key}")
                    _preview(key)
                warnings[key] = ui.label(HARD_TO_READ).classes("yt-hint yt-hint--warn")
                warnings[key].mark(f"colour-warning-{key}")
                warnings[key].set_visibility(not chat_colours.readable(colour))

    def apply(colours: dict[str, str]) -> None:
        ui.run_javascript(chat_colours.js(colours))
        status.clear()
        with status:
            saved_chip()

    def pick(key: str, value: str | None) -> None:
        if not chat_colours.valid(value) or value.lower() == chat_colours.current()[key]:
            return
        apply(chat_colours.save(key, value))
        warnings[key].set_visibility(not chat_colours.readable(value.lower()))

    def reset() -> None:
        colours = chat_colours.reset()
        apply(colours)
        show(colours)

    show(chat_colours.current())


def _preview(key: str) -> None:
    """A line in this channel's colour, styled like Live: it follows the colour at once."""
    name, text = _SAMPLES[key]
    with ui.element("div").classes(f"yt-line yt-line--{key} yt-colour-sample"):
        ui.label(NAMES[key]).classes(f"yt-line-ch yt-ch-{key}")
        with ui.element("div").classes("yt-line-body"):
            ui.label(f"{name}:" if name else "").classes(f"yt-line-name yt-ch-{key}")
            ui.label(text).classes("yt-line-text")
