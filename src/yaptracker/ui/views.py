"""The five views behind the icon rail. Placeholders until their milestones land."""

import time

import numpy as np
from nicegui import ui
from PIL import Image

from yaptracker import __version__, config, logs, paths, runtime
from yaptracker.capture.watcher import fps
from yaptracker.ui.calibrate import calibrate
from yaptracker.ui.components import button, saved_chip, set_button_label, switch
from yaptracker.ui.crew import crew_card
from yaptracker.ui.setup import setup_wizard, startup_card


def _header(title: str) -> None:
    with ui.element("header").classes("yt-header"):
        ui.label(title).classes("yt-h1")


def count(n: int, one: str, many: str) -> str:
    """'1 match', '2 matches', '0 yaps'."""
    return f"{n} {one if n == 1 else many}"


def _empty_card(title: str, hint: str) -> None:
    with ui.element("section").classes("yt-card"):
        with ui.element("div").classes("yt-card-head"):
            ui.label(title).classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            ui.label(hint).classes("yt-hint")


# Why capture stopped, for the Live banner (#75). Orange heads-up, not a red alarm.
_WHY = {
    "crash": "capture stopped",
    "no_frames": "no picture from Overwatch",
    "window_lost": "lost the Overwatch window",
}


# How an ended match shows in the Live header (#94).
_OUTCOMES = {"victory": "won", "defeat": "lost", "draw": "draw"}


# Chat line chips (docs/ui/mockup/Live): the channel, in its colour. Unsure typed lines say "Chat".
_CHANNELS = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}


def _chat_line(message, started_at: float | None) -> dict:
    """One row of the Live feed: time in the match, channel, who (you for own lines), text."""
    channel = message.channel if message.channel in _CHANNELS else "chat"
    with ui.element("div").classes(f"yt-line yt-line--{channel}"):
        seconds = max(0, int(message.ts - started_at)) if started_at else 0
        ui.label(f"{seconds // 60}:{seconds % 60:02d}").classes("yt-line-time")
        ui.label(_CHANNELS.get(channel, "Chat")).classes(f"yt-line-ch yt-ch-{channel}")
        name = ui.label().classes(f"yt-line-name yt-ch-{channel}")
        text = ui.label().classes("yt-line-text")
    row = {"name": name, "text": text, "shown": None}
    _fill_line(row, message)
    return row


def _fill_line(row: dict, message) -> None:
    shown = (message.speaker_raw, message.role, message.text)
    if shown == row["shown"]:
        return
    row["shown"] = shown
    # System lines carry the name in their text ("[gremlin.exe] started playing Overwatch.").
    who = message.speaker_raw if message.channel != "system" else ""
    who = "you" if who and message.role == "me" else who
    row["name"].set_text(f"{who}:" if who else "")
    row["text"].set_text(message.text)


# Pill colour per Live state: trouble shares the orange of paused - a heads-up, not an alarm.
_PILLS = {"paused": "paused", "trouble": "paused", "listening": "listening", "waiting": "waiting"}


def live() -> None:
    """Live, or the setup wizard in its place on the very first start (#76)."""
    if config.setup_state() is not None:
        _live()
        return
    body = ui.element("div").classes("yt-view")

    def done() -> None:
        body.clear()
        with body:
            _live()

    with body:
        setup_wizard(on_done=done)


def _live() -> None:
    watcher = runtime.watcher
    with ui.element("header").classes("yt-header"):
        ui.label("Live").classes("yt-h1")
        with ui.element("div").classes("yt-pill yt-pill--waiting").mark("status") as pill:
            ui.element("span").classes("yt-pill-dot")
            status = ui.label("Waiting for Overwatch")
        match_info = ui.label().classes("yt-meta").mark("match-info")
        meta = ui.label().classes("yt-hint").mark("status-meta")
        ui.element("div").classes("yt-grow")
        button(
            "New match", lambda: new_match(), keycap=runtime.NEW_MATCH_HOTKEY.replace("+", " ")
        ).mark("new-match")
        pause_button = button(
            "Pause", lambda: toggle_pause(), keycap=runtime.PAUSE_HOTKEY.replace("+", " ")
        )
        pause_button.mark("pause")
    with ui.element("div").classes("yt-banner yt-hidden").mark("health") as health_banner:
        health_text = ui.label().classes("yt-grow")
    with ui.element("div").classes("yt-banner yt-hidden").mark("size-hint") as size_hint:
        size_text = ui.label().classes("yt-grow")
        button("Got it", lambda: size_checked(), "quiet").mark("size-ok")
    if config.setup_state() == "skipped":  # once, after skipping setup (#76)
        with ui.element("div").classes("yt-banner").mark("setup-hint") as setup_hint:
            ui.label(
                "Setup skipped: I'm using the usual chat spot and don't know your name yet. "
                "Settings \u2192 Run setup takes 30 seconds."
            ).classes("yt-grow")
            button("Got it", lambda: setup_seen(), "quiet").mark("setup-ok")

        def setup_seen() -> None:
            config.save_setup_state("skipped-seen")
            setup_hint.classes(add="yt-hidden")

    with ui.element("div").classes("yt-columns"):
        with ui.element("section").classes("yt-card yt-card--chat").props('aria-label="Chat"'):
            with ui.element("div").classes("yt-card-head"):
                ui.label("This match").classes("yt-h2")
                yap_count = ui.label("0 yaps").classes("yt-meta").mark("yap-count")
                ui.element("div").classes("yt-grow")
                with ui.element("div").classes("yt-legend"):
                    for channel in ("Team", "Match", "Group", "System"):
                        ui.label(channel).classes(f"yt-ch-{channel.lower()}")
            with ui.element("div").classes("yt-card-body"):
                feed = ui.scroll_area(on_scroll=lambda e: follow(e)).classes("yt-lines")
                with feed:
                    lines = ui.element("div").classes("yt-lines-inner").mark("lines")
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
    chat = {"match": None, "rows": {}, "stick": True}

    def follow(e) -> None:
        """Auto-scroll pauses while you read further up, and comes back at the bottom."""
        chat["stick"] = e.vertical_size - e.vertical_position - e.vertical_container_size < 40

    def refresh_chat() -> None:
        match_id = runtime.matches.match_id if runtime.matches else None
        if match_id != chat["match"]:  # a new match starts with an empty feed
            chat.update(match=match_id, rows={})
            lines.clear()
        if match_id is None or runtime.store is None:
            yap_count.set_text("0 yaps")
            return
        messages = runtime.store.messages(match_id)
        added = False
        for message in messages:
            if message.id in chat["rows"]:
                _fill_line(chat["rows"][message.id], message)  # a better reading came in
            else:
                with lines:
                    chat["rows"][message.id] = _chat_line(message, runtime.matches.match_started_at)
                added = True
        yappers = {m.speaker_raw for m in messages if m.channel != "system" and m.speaker_raw}
        yaps, people = count(len(messages), "yap", "yaps"), count(len(yappers), "yapper", "yappers")
        yap_count.set_text(f"{yaps} \u00b7 {people}")
        if added and chat["stick"]:
            feed.scroll_to(percent=1.0)

    def toggle_pause() -> None:
        runtime.pause.toggle()
        refresh()

    def new_match() -> None:
        if runtime.matches is not None:
            runtime.matches.new_match()
        refresh()

    def size_checked() -> None:
        if runtime.window_size:
            config.mark_size_checked(*runtime.window_size)
        size_hint.classes(add="yt-hidden")

    def refresh() -> None:
        refresh_chat()
        paused = runtime.pause.paused
        capturing = watcher is not None and watcher.state == "capturing"
        gap = runtime.health.gap if runtime.health else None
        broken = gap is not None and gap.reason != "paused"  # the game runs, capture doesn't
        state = (
            "paused" if paused else "trouble" if broken else "listening" if capturing else "waiting"
        )
        pill.classes(
            add=f"yt-pill--{_PILLS[state]}",
            remove=" ".join(f"yt-pill--{p}" for p in set(_PILLS.values()) if p != _PILLS[state]),
        )
        status.set_text(
            {
                "paused": "Paused",
                "trouble": "Not recording",
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
                "trouble": "Overwatch is running, but I can't see it right now. Trying again.",
                "listening": "Ears open. Nobody's typing right now.",
                "waiting": "Waiting for Overwatch. I'll be right here.",
            }[state]
        )
        set_button_label(pause_button, "Resume" if paused else "Pause")
        where = runtime.matches.status() if runtime.matches else None
        if where is None:
            match_info.set_text("")
        else:
            if where.match is None:
                match_info.set_text(f"Session {where.session} \u00b7 no match yet")
            else:
                minutes, seconds = divmod(int(time.time() - where.started_at), 60)
                on_map = f" on {where.map_name.title()}" if where.map_name else ""
                when = (
                    _OUTCOMES.get(where.outcome, "over")
                    if where.ended
                    else f"{minutes}:{seconds:02d} in"
                )
                match_info.set_text(
                    f"Session {where.session} \u00b7 Match {where.match}{on_map} \u00b7 {when}"
                )
        if broken:  # paused has its own pill (#20)
            since = time.strftime("%H:%M", time.localtime(gap.since))
            health_text.set_text(
                f"Not recording since {since} ({_WHY[gap.reason]}), trying again\u2026"
            )
            health_banner.classes(remove="yt-hidden")
        else:
            health_banner.classes(add="yt-hidden")
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
                    button("Run setup again", open_setup, "quiet").mark("run-setup")
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
            startup_card()
            with ui.element("section").classes("yt-card").mark("data"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("Your data").classes("yt-h2")
                    ui.element("div").classes("yt-grow")
                    open_logs = button("Open logs", lambda: logs.open_folder()).mark("open-logs")
                    if not logs.folder_opens():
                        open_logs.props('disabled title="Opens Explorer, so only on Windows"')
                with ui.element("div").classes("yt-card-body"):
                    ui.label(str(paths.data_dir())).classes("yt-meta yt-mono")
                    if runtime.store is not None:
                        stats, db = runtime.store.stats(), paths.db_file()
                        size = db.stat().st_size / 1_000_000 if db.exists() else 0.0
                        ui.label(
                            f"{count(stats.messages, 'yap', 'yaps')}, "
                            f"{count(stats.matches, 'match', 'matches')}, "
                            f"{count(stats.players, 'yapper', 'yappers')}, {size:.1f} MB"
                        ).classes("yt-meta").mark("data-stats")
                    ui.label(
                        "A copy goes to the backups folder before every database update. "
                        "Updating YapTracker never touches this folder."
                    ).classes("yt-hint")
            with ui.element("section").classes("yt-card").mark("debug"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("Debug samples").classes("yt-h2")
                    ui.element("div").classes("yt-grow")
                    open_debug = button(
                        "Open folder", lambda: logs.open_folder(paths.debug_dir())
                    ).mark("open-debug")
                    if not logs.folder_opens():
                        open_debug.props('disabled title="Opens Explorer, so only on Windows"')
                with ui.element("div").classes("yt-card-body"):
                    switch(
                        "Collect debug samples", config.debug_samples(), config.save_debug_samples
                    ).mark("debug-switch")
                    size = runtime.debug.size_bytes() / 1_000_000 if runtime.debug else 0.0
                    ui.label(
                        f"Debug samples: {size:.1f} MB, kept 14 days and 1 GB at most"
                    ).classes("yt-meta").mark("debug-size")
                    ui.label(
                        "Match starts and ends, and screens I might have missed, so they can be "
                        "fixed later. Other players' names are in there: it never leaves this PC."
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

    def open_setup() -> None:
        body.clear()
        with body:
            setup_wizard(on_done=overview)

    overview()
