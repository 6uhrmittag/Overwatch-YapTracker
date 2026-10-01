"""The yap snap preview (#64): exactly the PNG that gets saved, with the name/footer switches."""

from nicegui import ui

from yaptracker import logs, paths
from yaptracker.snaps import render, save, snap_lines
from yaptracker.ui.components import button, switch


def snap_dialog(messages: list, footer: str) -> None:
    state = {"hide": True, "crew": False, "footer": True, "image": None}
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-snap"):
        with ui.element("div").classes("yt-card-body"):
            ui.label("Your yap snap").classes("yt-h2")
            preview = ui.image().classes("yt-snap-preview").mark("snap-preview")
            with ui.element("div").classes("yt-row"):
                switch("Hide names", True, lambda on: flip("hide", on)).mark("snap-hide")
                switch("Keep me & my crew", False, lambda on: flip("crew", on)).mark("snap-crew")
                switch("Match and date", True, lambda on: flip("footer", on)).mark("snap-footer")
            ui.label(
                "Hidden names become Player 1, 2, 3... in the lines and in the text, so the snap "
                "is safe to post anywhere."
            ).classes("yt-hint")
            with ui.element("div").classes("yt-row"):
                button("Save PNG", lambda: keep(), "primary").mark("snap-save")
                saved = ui.label().classes("yt-hint yt-mono").mark("snap-saved")
                ui.element("div").classes("yt-grow")
                button("Close", dialog.close, "quiet")

    def draw() -> None:
        lines = snap_lines(messages, hide_names=state["hide"], keep_crew=state["crew"])
        state["image"] = render(lines, footer if state["footer"] else None)
        preview.set_source(state["image"])
        saved.set_text("")

    def flip(key: str, on: bool) -> None:
        state[key] = on
        draw()

    def keep() -> None:
        path = save(state["image"], paths.pictures_dir())
        saved.set_text(f"Saved to {path}")
        if logs.folder_opens():
            logs.open_folder(path.parent)

    dialog.on_value_change(lambda e: None if e.value else dialog.delete())  # gone once closed
    draw()
    dialog.open()
