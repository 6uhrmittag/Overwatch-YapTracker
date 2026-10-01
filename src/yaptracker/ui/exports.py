"""Settings -> Export: your yappers as players.md + players.json (#31), and everything as
yaptracker-export.json (#69). The big one runs in the background with a progress line."""

import time

from nicegui import run, ui

from yaptracker import logs, paths, runtime
from yaptracker.export import export_all, export_folder, export_players
from yaptracker.ui.components import button


def export_card() -> None:
    with ui.element("section").classes("yt-card").mark("export"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Export").classes("yt-h2")
            ui.element("div").classes("yt-grow")
            button("Export yappers", lambda: export(), "quiet").mark("export-players")
            everything = button("Export everything", lambda: export_everything()).mark("export-all")
        with ui.element("div").classes("yt-card-body"):
            ui.label(
                "Yappers: everyone you met, with your verdicts, notes and every spelling I read, "
                "as players.md (for your notes app) and players.json (for scripts)."
            ).classes("yt-hint")
            ui.label(
                "Everything: every session, match and yap, your yappers and the times nothing was "
                "recorded, as one documented JSON file. Yours to keep, script or share."
            ).classes("yt-hint")
            result = ui.label().classes("yt-meta yt-mono").mark("export-result")
    state = {"done": 0, "total": 0, "running": False}

    def export() -> None:
        if runtime.store is None:
            return
        now = time.time()
        folder = export_folder(paths.export_dir(), now)
        files = export_players(runtime.store, folder, now)
        result.set_text(f"Saved to {folder}: {', '.join(f.name for f in files)}")
        if logs.folder_opens():
            logs.open_folder(folder)

    def progress(done: int, total: int) -> None:  # from the export thread
        state["done"], state["total"] = done, total

    def show_progress() -> None:
        if state["running"] and state["total"]:
            result.set_text(f"Exporting… {100 * state['done'] // state['total']} %")

    async def export_everything() -> None:
        if runtime.store is None or state["running"]:
            return
        state.update(done=0, total=0, running=True)
        everything.props("loading")
        result.set_text("Exporting…")
        now = time.time()
        try:
            path = await run.io_bound(
                export_all, runtime.store, export_folder(paths.export_dir(), now), now, progress
            )
        finally:
            state["running"] = False
            everything.props(remove="loading")
        result.set_text(f"Saved to {path}")
        if logs.folder_opens():
            logs.open_folder(path.parent)

    ui.timer(0.5, show_progress)
