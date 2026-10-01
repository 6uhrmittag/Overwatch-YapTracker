"""Settings -> Export (#31): your yappers, verdicts and notes as players.md and players.json."""

import time

from nicegui import ui

from yaptracker import logs, paths, runtime
from yaptracker.export import export_folder, export_players
from yaptracker.ui.components import button


def export_card() -> None:
    with ui.element("section").classes("yt-card").mark("export"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Export").classes("yt-h2")
            ui.element("div").classes("yt-grow")
            button("Export yappers", lambda: export()).mark("export-players")
        with ui.element("div").classes("yt-card-body"):
            ui.label(
                "Everyone you met, with your verdicts, notes and every spelling I read, as "
                "players.md (for your notes app) and players.json (for scripts)."
            ).classes("yt-hint")
            result = ui.label().classes("yt-meta yt-mono").mark("export-result")

    def export() -> None:
        if runtime.store is None:
            return
        now = time.time()
        folder = export_folder(paths.export_dir(), now)
        files = export_players(runtime.store, folder, now)
        result.set_text(f"Saved to {folder}: {', '.join(f.name for f in files)}")
        if logs.folder_opens():
            logs.open_folder(folder)
