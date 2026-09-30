"""The five views behind the icon rail. Placeholders until their milestones land."""

from nicegui import ui

from yaptracker import __version__, config
from yaptracker.ui.calibrate import calibrate
from yaptracker.ui.components import button, saved_chip
from yaptracker.ui.crew import crew_card


def _header(title: str) -> None:
    with ui.element("header").classes("yt-header"):
        ui.label(title).classes("yt-h1")


def _empty_card(title: str, hint: str) -> None:
    with ui.element("section").classes("yt-card"):
        with ui.element("div").classes("yt-card-head"):
            ui.label(title).classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            ui.label(hint).classes("yt-hint")


def live() -> None:
    with ui.element("header").classes("yt-header"):
        ui.label("Live").classes("yt-h1")
        with ui.element("div").classes("yt-pill yt-pill--waiting"):
            ui.element("span").classes("yt-pill-dot")
            ui.label("Waiting for Overwatch")
    with ui.element("div").classes("yt-columns"):
        with ui.element("section").classes("yt-card yt-card--chat").props('aria-label="Chat"'):
            with ui.element("div").classes("yt-card-head"):
                ui.label("This match").classes("yt-h2")
                ui.label("0 yaps").classes("yt-meta")
                ui.element("div").classes("yt-grow")
                with ui.element("div").classes("yt-legend"):
                    for channel in ("Team", "Match", "Group", "System"):
                        ui.label(channel).classes(f"yt-ch-{channel.lower()}")
            with ui.element("div").classes("yt-card-body"):
                ui.label("No yaps yet. Suspiciously quiet lobby.").classes("yt-hint")
        with ui.element("aside").classes("yt-aside").props('aria-label="Familiar faces"'):
            with ui.element("div").classes("yt-card yt-card--placeholder"):
                with ui.element("div").classes("yt-card-body"):
                    ui.label("Look who's back!").classes("yt-h2")
                    ui.label(
                        "When someone you've met before starts yapping, their card pops up here."
                    ).classes("yt-hint")


def yappers() -> None:
    _header("Yappers")
    _empty_card("Nobody yet", "Play a match and the people who yap will show up here.")


def sessions() -> None:
    _header("Sessions")
    _empty_card("No sessions yet", "Every evening of play lands here, match by match.")


def search() -> None:
    _header("Search")
    _empty_card("Nothing to search yet", "Every yap ever read will be findable here.")


def settings() -> None:
    body = ui.element("div").classes("yt-view")

    def overview(saved: bool = False) -> None:
        body.clear()
        with body:
            _header("Settings")
            with ui.element("section").classes("yt-card").mark("chat-box"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("Chat box").classes("yt-h2")
                    if saved:
                        saved_chip()
                    ui.element("div").classes("yt-grow")
                    button("Calibrate", open_calibration).mark("calibrate")
                with ui.element("div").classes("yt-card-body"):
                    regions = config.saved_chat_regions()
                    for resolution, r in regions.items():
                        ui.label(
                            f"{resolution}: {r.width} \u00d7 {r.height} px at {r.x}, {r.y}"
                        ).classes("yt-meta")
                    if not regions:
                        ui.label(
                            "Not calibrated yet. I'll use the usual spot, which fits 16:9 screens."
                        ).classes("yt-hint")
            crew_card()
            with ui.element("section").classes("yt-card").mark("about"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("About").classes("yt-h2")
                with ui.element("div").classes("yt-card-body"):
                    ui.label(f"YapTracker {__version__}").classes("yt-meta")
                    ui.label("Everything stays on this PC. No cloud, no telemetry.").classes(
                        "yt-hint"
                    )

    def open_calibration() -> None:
        body.clear()
        with body:
            calibrate(on_done=overview)

    overview()
