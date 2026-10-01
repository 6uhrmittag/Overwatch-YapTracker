"""Who's that? (#27): a name off the scoreboard, typed, and you know who it is. Bottom right in
Live (docs/ui/mockup/Live); Ctrl+Alt+F brings YapTracker forward with this box focused."""

import time

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.components import button, sticker, when
from yaptracker.ui.yappers import matching

SHOWN = 5  # results under the box; the Yappers view has the rest


def lookup_card() -> ui.input:
    """The card; returns its search box, so Ctrl+Alt+F can focus it."""
    with ui.element("section").classes("yt-card yt-lookup").mark("lookup"):
        with ui.element("div").classes("yt-card-body"):
            ui.label("Who's that?").classes("yt-h2")
            with ui.element("div").classes("yt-row yt-lookup-box"):
                box = (
                    ui.input(placeholder="Type a name from the scoreboard")
                    .props("dense borderless clearable debounce=150")
                    .classes("yt-grow")
                    .mark("lookup-box")
                )
                ui.label(runtime.LOOKUP_HOTKEY.replace("+", " ")).classes("yt-keycap")
            results = ui.element("div").classes("yt-lookup-results").mark("lookup-results")

    def open_player(player_id: int) -> None:
        ui.context.client.yt_show("yappers", player_id=player_id)

    def add(name: str) -> None:
        store = runtime.store
        open_player(store.add_player(name, time.time()))

    def search(e) -> None:
        query = (e.value or "").strip()
        results.clear()
        store = runtime.store
        if not query or store is None:
            return
        found = matching(store.players(), store.player_names(), query)[:SHOWN]
        with results:
            for player in found:
                row = ui.element("div").classes("yt-lookup-row").mark("lookup-result")
                row.on("click", lambda pid=player.id: open_player(pid))
                with row:
                    ui.label(player.display_name).classes("yt-lookup-name")
                    if player.verdict:
                        sticker(player.verdict)
                    ui.element("div").classes("yt-grow")
                    ui.label(f"last met {when(player.last_seen)}").classes("yt-meta")
            if not found:
                ui.label("Never met them. Want to add them?").classes("yt-hint")
                button(f"Add {query}", lambda: add(query)).mark("lookup-add")

    box.on_value_change(search)
    return box
