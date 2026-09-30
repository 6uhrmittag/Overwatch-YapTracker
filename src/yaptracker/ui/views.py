"""The five views behind the icon rail. Placeholders until their milestones land."""

import numpy as np
from nicegui import ui
from PIL import Image

from yaptracker import __version__, autostart, config, runtime
from yaptracker.capture.watcher import fps
from yaptracker.ui.calibrate import calibrate
from yaptracker.ui.components import button, saved_chip, set_button_label, switch
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
    watcher = runtime.watcher
    with ui.element("header").classes("yt-header"):
        ui.label("Live").classes("yt-h1")
        with ui.element("div").classes("yt-pill yt-pill--waiting").mark("status") as pill:
            ui.element("span").classes("yt-pill-dot")
            status = ui.label("Waiting for Overwatch")
        meta = ui.label().classes("yt-meta").mark("status-meta")
        ui.element("div").classes("yt-grow")
        pause_button = button(
            "Pause", lambda: toggle_pause(), keycap=runtime.PAUSE_HOTKEY.replace("+", " ")
        )
        pause_button.mark("pause")
    with ui.element("div").classes("yt-banner yt-hidden").mark("size-hint") as size_hint:
        size_text = ui.label().classes("yt-grow")
        button("Got it", lambda: size_checked(), "quiet").mark("size-ok")
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
                hint = ui.label("Waiting for Overwatch. I'll be right here.").classes("yt-hint")
        with ui.element("aside").classes("yt-aside").props('aria-label="Familiar faces"'):
            with ui.element("div").classes("yt-card yt-card--placeholder"):
                with ui.element("div").classes("yt-card-body"):
                    ui.label("Look who's back!").classes("yt-h2")
                    ui.label(
                        "When someone you've met before starts yapping, their card pops up here."
                    ).classes("yt-hint")
            with ui.element("section").classes("yt-card yt-hidden").mark("preview") as preview:
                with ui.element("div").classes("yt-card-body"):
                    ui.label("What I see").classes("yt-h2")
                    picture = ui.image().classes("yt-crop").props("no-spinner no-transition")
                    picture_info = ui.label().classes("yt-meta")

    meter = fps(watcher) if watcher else (lambda: 0.0)
    shown = {"frame": None}

    def toggle_pause() -> None:
        runtime.pause.toggle()
        refresh()

    def size_checked() -> None:
        if runtime.window_size:
            config.mark_size_checked(*runtime.window_size)
        size_hint.classes(add="yt-hidden")

    def refresh() -> None:
        paused = runtime.pause.paused
        capturing = watcher is not None and watcher.state == "capturing"
        state = "paused" if paused else ("listening" if capturing else "waiting")
        pill.classes(
            add=f"yt-pill--{state}",
            remove=" ".join(
                f"yt-pill--{s}" for s in ("paused", "listening", "waiting") if s != state
            ),
        )
        status.set_text(
            {
                "paused": "Paused",
                "listening": "Listening for yaps",
                "waiting": "Waiting for Overwatch",
            }[state]
        )
        if paused:
            minutes = max(1, round(runtime.pause.remaining_s() / 60))
            meta.set_text(f"until next match, {minutes} min at most")
        elif capturing:
            skipped = f", {runtime.changes.skipped_share:.0%} skipped" if runtime.changes else ""
            meta.set_text(f"{meter():.1f} fps{skipped}")
        else:
            meta.set_text((watcher.last_error or "") if watcher else "")
        hint.set_text(
            {
                "paused": "Ears covered. Nothing is being saved.",
                "listening": "Ears open. Nobody's typing right now.",
                "waiting": "Waiting for Overwatch. I'll be right here.",
            }[state]
        )
        set_button_label(pause_button, "Resume" if paused else "Pause")
        size = runtime.window_size
        if capturing and size and config.size_needs_check(*size):
            size_text.set_text(
                f"Overwatch runs at {size[0]}\u00d7{size[1]} now. I rescaled the chat box to fit; "
                "a 10-second look in Settings \u2192 Calibrate won't hurt."
            )
            size_hint.classes(remove="yt-hidden")
        else:
            size_hint.classes(add="yt-hidden")
        frame = watcher.last_frame if watcher else None
        if state == "listening" and frame is not None:
            preview.classes(remove="yt-hidden")
            if frame is not shown["frame"]:
                shown["frame"] = frame
                picture.set_source(Image.fromarray(np.ascontiguousarray(frame.image[:, :, ::-1])))
                height, width = frame.image.shape[:2]
                picture_info.set_text(
                    f"Chat box {width} \u00d7 {height} px, {watcher.frames} frames"
                )
        else:
            preview.classes(add="yt-hidden")

    ui.timer(1.0, refresh)
    refresh()


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
                    boxes = config.saved_chat_boxes()
                    for ratio, saved in boxes.items():
                        w, h = saved.calibrated_at
                        r = saved.box.to_pixels(w, h)
                        drawn = (
                            f"drawn at {w}\u00d7{h}, {r.width} \u00d7 {r.height} px at {r.x}, {r.y}"
                        )
                        ui.label(f"{ratio} screens: {drawn}; other sizes scale along").classes(
                            "yt-meta"
                        )
                    if not boxes:
                        ui.label(
                            "Not calibrated yet. I'll use the usual spot, which fits 16:9 screens."
                        ).classes("yt-hint")
            crew_card()
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
