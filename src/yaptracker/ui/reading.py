"""Settings -> Reading (#152): how the chat is read during Competitive and other matches (#331),
and how often. Applies at once."""

from nicegui import ui

from yaptracker import config, runtime
from yaptracker import reading_mode as modes

_GAPS = {1.5: "Every 1.5 s", 3.0: "Every 3 s"}
_MODES = {
    modes.AFTER: "After the match",
    modes.LIGHT: "Live, light",
    modes.BEST: "Live, best quality",
}


def reading_card() -> None:
    with ui.element("section").classes("yt-card").mark("reading"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Reading").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Competitive").classes("yt-setting-name")
                competitive = ui.element("div").classes("yt-seg").mark("reading-competitive")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Other matches").classes("yt-setting-name")
                other = ui.element("div").classes("yt-seg").mark("reading-other")
            ui.label(
                "How I read the chat during a match. After the match costs your game nothing: "
                "I keep the chat pictures and read them once it's over, so faces show up after "
                "the match. Light reading costs almost nothing and shows faces live, but misses "
                "some words; I fix it up after the match with the best reader. Between matches "
                "I always read with the best quality: the game is idle then."
            ).classes("yt-hint")
            ui.label(
                "Competitive is spotted at hero select. If I missed hero select, the match counts "
                "as 'other'."
            ).classes("yt-hint")
            problem = ui.label().classes("yt-hint yt-hidden").mark("reading-light-problem")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Read the chat").classes("yt-setting-name")
                gaps = ui.element("div").classes("yt-seg").mark("reading-gaps")
            ui.label(
                "Every 3 s is lighter on the CPU, but a fast burst of chat can push a line out "
                "of the box before I read it."
            ).classes("yt-hint")

    def segment(container, options: dict, chosen, choose, key: str, disabled=()) -> None:
        container.clear()
        with container:
            for value, label in options.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"{key}-{value}")
                if value == chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                if value in disabled:
                    item.props('disabled title="Windows only"')
                with item:
                    ui.label(label)
                item.on("click", lambda value=value: choose(value))

    def choose(kind: str, choice: str) -> None:
        config.save_reading(kind, choice)  # the next read already uses it
        render()

    def choose_gap(seconds: float) -> None:
        config.save_read_every_s(seconds)
        if runtime.reader is not None:
            runtime.reader.min_gap_s = seconds  # the next read already waits this long
        render()

    def render() -> None:
        for kind, container in (("competitive", competitive), ("other", other)):
            chosen = config.reading(kind)
            segment(container, _MODES, chosen, lambda c, kind=kind: choose(kind, c), kind)
        why = runtime.reading.light_problem if runtime.reading is not None else None
        problem.set_text(f"Light reading can't run here ({why}): I read with the best quality.")
        problem.classes(**{"remove" if why else "add": "yt-hidden"})
        segment(gaps, _GAPS, config.read_every_s(), choose_gap, "gap")

    render()
