"""The five views behind the icon rail. Placeholders until their milestones land."""

import html
import time

import numpy as np
from nicegui import run, ui
from PIL import Image

from yaptracker import __version__, config, logs, paths, runtime
from yaptracker.capture.stats import CAPTURE
from yaptracker.capture.watcher import fps
from yaptracker.glyphs import GLYPH
from yaptracker.store.backups import last_backup
from yaptracker.ui.calibrate import calibrate
from yaptracker.ui.components import (
    SPICY,
    button,
    count,
    saved_chip,
    set_button_label,
    switch,
)
from yaptracker.ui.crew import crew_card
from yaptracker.ui.exports import export_card
from yaptracker.ui.familiar_cards import familiar_card
from yaptracker.ui.hotkeys import hotkeys_card
from yaptracker.ui.lookup import lookup_card
from yaptracker.ui.reading import reading_card
from yaptracker.ui.setup import setup_wizard, startup_card


def _header(title: str) -> None:
    with ui.element("header").classes("yt-header"):
        ui.label(title).classes("yt-h1")


# Why capture stopped, for the Live banner (#75). Orange heads-up, not a red alarm.
_WHY = {
    "crash": "capture stopped",
    "no_frames": "no picture from Overwatch",
    "window_lost": "lost the Overwatch window",
}
# ... and what to do about it (#137): mostly nothing, it fixes itself.
_TODO = {
    "crash": "I'm restarting it. If this keeps coming back, Settings \u2192 Open logs shows why.",
    "no_frames": "Is Overwatch minimised? Bring it up once, I keep trying.",
    "window_lost": "I'm looking for it again, nothing to do.",
}


def _backup_text() -> str:
    """'Last backup: today 18:02 · 7 kept' (#125)."""
    newest = last_backup(paths.backup_dir())
    if newest is None:
        return "No daily backup yet: the first one is made when Overwatch isn't running."
    when, kept = newest
    day = time.strftime("%Y-%m-%d", time.localtime(when))
    today = time.strftime("%Y-%m-%d")
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    label = {today: "today", yesterday: "yesterday"}.get(day, day)
    return f"Last backup: {label} {time.strftime('%H:%M', time.localtime(when))} \u00b7 {kept} kept"


# How an ended match shows in the Live header (#94).
_OUTCOMES = {"victory": "won", "defeat": "lost", "draw": "draw"}


# Chat line chips (docs/ui/mockup/Live): the channel, in its colour. Unsure typed lines say "Chat".
_CHANNELS = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}


def chat_line(message, started_at: float | None, verdict: str | None = None, on_click=None) -> dict:
    """One chat row (Live feed, transcripts #29): time in the match, channel, who (you for own
    lines, a crew tag for crew), text. Known players get their verdict colour (docs/ui.md)."""
    channel = message.channel if message.channel in _CHANNELS else "chat"
    known = f" yt-line--known yt-known--{verdict}" if verdict else ""
    with (
        ui.element("div")
        .classes(f"yt-line yt-line--{channel}{known}")
        .mark(f"chat-line line-{message.id}") as line
    ):
        seconds = max(0, int(message.ts - started_at)) if started_at else 0
        ui.label(f"{seconds // 60}:{seconds % 60:02d}").classes("yt-line-time")
        ui.label(_CHANNELS.get(channel, "Chat")).classes(f"yt-line-ch yt-ch-{channel}")
        name = ui.label().classes(f"yt-line-name yt-ch-{channel}")
        if message.role == "crew":
            ui.label("crew").classes("yt-crew-badge")
        text = ui.html("", sanitize=False).classes("yt-line-text")
    if on_click:  # picking lines for a snap (#64): on_click(shift)
        line.on("click", lambda e: on_click(bool((e.args or {}).get("shiftKey"))), ["shiftKey"])
    else:
        line.on("click", lambda: show_picture(message))  # how it looked (#120, #128)
    row = {"name": name, "text": text, "shown": None, "line": line}
    _fill_line(row, message)
    return row


def show_picture(message) -> None:
    """A click on a line: its picture (#120, #128) and the spicy switch (#77)."""
    message = runtime.store.message(message.id) if runtime.store else None
    if message is None:
        return
    path = runtime.pictures.path(message.id, message.ts) if runtime.pictures else None
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-picture"):
        with ui.element("div").classes("yt-card-body"):
            if path is not None and path.exists():
                ui.image(path).classes("yt-picture-image").mark("line-picture")
                ui.label("The line as it looked in Overwatch.").classes("yt-hint")
            spicy = message.flagged is not None
            ui.label(
                "Overwatch marked this line ([Report])." if message.flagged == "overwatch"
                else "You marked this line as spicy." if spicy
                else "A bit much? Mark it, and you get a heads-up when they're back."
            ).classes("yt-hint")  # fmt: skip

            def toggle() -> None:
                runtime.store.set_flag(message.id, None if spicy else "manual")
                dialog.close()

            button("Not spicy" if spicy else "Mark as spicy", toggle).mark("spicy-toggle")
    dialog.on_value_change(lambda e: None if e.value else dialog.delete())  # gone once closed
    dialog.open()


def _fill_line(row: dict, message) -> None:
    shown = (message.speaker_raw, message.role, message.text, message.flagged)
    if shown == row["shown"]:
        return
    row["shown"] = shown
    # System lines carry the name in their text ("[gremlin.exe] started playing Overwatch.").
    who = message.speaker_raw if message.channel != "system" else ""
    who = "you" if who and message.role == "me" else who
    row["name"].set_text(f"{who}:" if who else "")
    # Escaped text; an emoji or icon OCR couldn't spell shows as a ◇ chip (#128).
    chip = f'<span class="yt-glyph" title="An emoji or icon: click for the picture">{GLYPH}</span>'
    text = html.escape(message.text, quote=False).replace(GLYPH, chip)
    if message.flagged:  # spicy (#77): a small chili, no judgement
        text += " " + SPICY
    row["text"].set_content(text)


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
        peek = button("Show what I see", lambda: toggle_preview(), "quiet").mark("toggle-preview")
        button("New match", lambda: new_match(), keycap=runtime.keycap("new_match")).mark(
            "new-match"
        )
        pause_button = button("Pause", lambda: toggle_pause(), keycap=runtime.keycap("pause"))
        pause_button.mark("pause")
    with ui.element("div").classes("yt-banner yt-hidden").mark("health") as health_banner:
        health_text = ui.label().classes("yt-grow")
    with ui.element("div").classes("yt-banner yt-hidden").mark("no-name") as name_hint:
        ui.label("I don't know your name yet, so I might greet you as a stranger.").classes(
            "yt-grow"
        )
        button("Add my name", lambda: ui.context.client.yt_show("settings"), "quiet").mark(
            "add-my-name"
        )
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
            with ui.element("div").classes("yt-card-body yt-feed"):
                # follows new yaps in the browser (static/follow.js, #166) until you scroll up
                with ui.element("div").classes("yt-lines yt-follow").mark("feed"):
                    lines = ui.element("div").classes("yt-lines-inner").mark("lines")
                ui.label("New yaps \u2193").classes("yt-new-yaps yt-hidden").mark("new-yaps")
                hint = ui.label("Waiting for Overwatch. I'll be right here.").classes("yt-hint")
        with ui.element("aside").classes("yt-aside").props('aria-label="Familiar faces"'):
            faces = ui.element("div").classes("yt-faces").mark("faces")
            with ui.element("section").classes("yt-card yt-hidden").mark("preview") as preview:
                with ui.element("div").classes("yt-card-body"):
                    with ui.element("div").classes("yt-row"):
                        ui.label("What I see").classes("yt-h2 yt-grow")
                        button("Hide", lambda: toggle_preview(False), "quiet").mark("preview-hide")
                    picture = ui.image().classes("yt-crop").props("no-spinner no-transition")
                    picture_info = ui.label().classes("yt-meta")
            ui.element("div").classes("yt-grow")
            lookup = lookup_card()  # bottom right, as in the Live mockup (#27)
    ui.context.client.yt_focus_lookup = lambda: lookup.run_method("focus")

    meter = fps(watcher) if watcher else (lambda: 0.0)
    shown = {"frame": None}
    chat = {"match": None, "rows": {}}

    def refresh_chat() -> None:
        match_id = runtime.matches.match_id if runtime.matches else None
        if match_id != chat["match"]:  # a new match starts with an empty feed
            chat.update(match=match_id, rows={})
            lines.clear()
        if match_id is None or runtime.store is None:
            yap_count.set_text("0 yaps")
            return
        messages = runtime.store.messages(match_id)
        for message in messages:
            if message.id in chat["rows"]:
                _fill_line(chat["rows"][message.id], message)  # a better reading came in
            else:
                with lines:
                    chat["rows"][message.id] = chat_line(message, runtime.matches.match_started_at)
        yappers = {m.speaker_raw for m in messages if m.channel != "system" and m.speaker_raw}
        yaps, people = count(len(messages), "yap", "yaps"), count(len(yappers), "yapper", "yappers")
        yap_count.set_text(f"{yaps} \u00b7 {people}")

    def toggle_pause() -> None:
        runtime.pause.toggle()
        refresh()

    def new_match() -> None:
        if runtime.matches is not None:
            runtime.matches.new_match()
        refresh()

    peeking = {"closed": False}  # you hid it: it doesn't open by itself again on this page

    def toggle_preview(on: bool | None = None) -> None:
        """The "What I see" picture (#163): hidden by default, it distracts during play."""
        on = not config.show_what_i_see() if on is None else on
        config.save_show_what_i_see(on)
        peeking["closed"] = not on
        refresh()

    def size_checked() -> None:
        if runtime.window_size:
            config.mark_size_checked(*runtime.window_size)
        size_hint.classes(add="yt-hidden")

    shown_faces = {"cards": None}

    def refresh_faces() -> None:
        """Cards for familiar faces (#26), newest on top; the placeholder when there are none."""
        cards = runtime.familiar.active() if runtime.familiar else []
        key = [(c.player_id, c.shown_at) for c in cards]
        if key == shown_faces["cards"]:
            return
        shown_faces["cards"] = key
        faces.clear()
        with faces:
            for card in cards:
                familiar_card(
                    card,
                    on_open=lambda pid=card.player_id: ui.context.client.yt_show(
                        "yappers", player_id=pid
                    ),
                    on_dismiss=lambda pid=card.player_id: dismiss(pid),
                )
            if not cards:
                with ui.element("div").classes("yt-card yt-card--placeholder"):
                    with ui.element("div").classes("yt-card-body"):
                        ui.label("Look who's back!").classes("yt-h2")
                        ui.label(
                            "When someone you've met before starts yapping, their card pops up "
                            "here."
                        ).classes("yt-hint")

    def dismiss(player_id: int) -> None:
        runtime.familiar.dismiss(player_id)
        refresh_faces()

    def refresh() -> None:
        refresh_chat()
        refresh_faces()
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
            meta.set_text("")  # the banner says what's wrong and what to do; details are in the log
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
                f"Not recording since {since} ({_WHY[gap.reason]}). {_TODO[gap.reason]}"
            )
            health_banner.classes(remove="yt-hidden")
        else:
            health_banner.classes(add="yt-hidden")
        # no own name: your own lines would greet you with "Look who's back!" (#168)
        name_hint.classes(**{"add" if config.identity().me else "remove": "yt-hidden"})
        size = runtime.window_size
        check_size = bool(capturing and size and config.size_needs_check(*size))
        if check_size:
            size_text.set_text(
                f"Overwatch runs at {size[0]}\u00d7{size[1]} now. I rescaled the chat box to fit; "
                "a 10-second look in Settings \u2192 Calibrate won't hurt."
            )
            size_hint.classes(remove="yt-hidden")
        else:
            size_hint.classes(add="yt-hidden")
        frame = watcher.last_frame if watcher else None
        wanted = config.show_what_i_see() or (check_size and not peeking["closed"])
        set_button_label(peek, "Hide what I see" if config.show_what_i_see() else "Show what I see")
        if state == "listening" and frame is not None and wanted:  # hidden: no pictures sent
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
                    else:
                        ui.label(
                            "Chat moved, or lines come out cut off? Calibrate again: one click "
                            "while Overwatch runs."
                        ).classes("yt-hint")
            reading_card()
            crew_card()
            startup_card()
            hotkeys_card()
            with ui.element("section").classes("yt-card").mark("data"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("Your data").classes("yt-h2")
                    ui.element("div").classes("yt-grow")
                    open_data = button(
                        "Open data folder", lambda: logs.open_folder(paths.data_dir()), "quiet"
                    ).mark("open-data")
                    open_logs = button("Open logs", lambda: logs.open_folder()).mark("open-logs")
                    if not logs.folder_opens():
                        for b in (open_data, open_logs):
                            b.props('disabled title="Opens Explorer, so only on Windows"')
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
                    with ui.element("div").classes("yt-row"):
                        backup_info = (
                            ui.label(_backup_text()).classes("yt-meta").mark("backup-info")
                        )
                        backup_now = button("Back up now", lambda: back_up(), "quiet").mark(
                            "backup-now"
                        )
                        if runtime.backups is None:
                            backup_now.props("disabled")
                        open_backups = button(
                            "Open backups", lambda: logs.open_folder(paths.backup_dir()), "quiet"
                        ).mark("open-backups")
                        if not logs.folder_opens():
                            open_backups.props("disabled")

                    async def back_up() -> None:
                        backup_now.props("loading")
                        await run.io_bound(runtime.backups.now)
                        backup_now.props(remove="loading")
                        backup_info.set_text(_backup_text())

                    switch(
                        "Keep line pictures", config.line_pictures(), config.save_line_pictures
                    ).mark("pictures-switch")
                    pictures = runtime.pictures.size_bytes() / 1_000_000 if runtime.pictures else 0
                    ui.label(f"Line pictures: {pictures:.1f} MB, 2 GB at most").classes(
                        "yt-meta"
                    ).mark("pictures-size")
                    ui.label(
                        "Each chat line as it looked, so hearts and icons OCR can't spell are kept "
                        "(click a line in Live). Switch off only if disk space is tight."
                    ).classes("yt-hint")
                    ui.label(
                        "A copy goes to the backups folder every day (never during a match) and "
                        "before every database update. Updating YapTracker never touches this "
                        "folder."
                    ).classes("yt-hint")
            export_card()
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
                        "Match starts and ends, screens I might have missed and chat I found hard, "
                        "so they can be fixed later. Other players' names are in there: it never "
                        "leaves this PC."
                    ).classes("yt-hint")
                    with ui.element("div").classes("yt-row"):
                        button(
                            "Save the last 20 s",
                            lambda: save_chat(),
                            keycap=runtime.keycap("save"),
                        ).mark("save-chat")
                        saved_chat = ui.label().classes("yt-hint").mark("save-chat-result")

                    def save_chat() -> None:
                        sample = runtime.debug.save_chat() if runtime.debug else None
                        saved_chat.set_text(
                            f"Kept in {sample.parent.name}\\{sample.name}."
                            if sample
                            else "Nothing read in the last 20 s: play a bit, then press it."
                        )

            with ui.element("section").classes("yt-card").mark("about"):
                with ui.element("div").classes("yt-card-head"):
                    ui.label("About").classes("yt-h2")
                with ui.element("div").classes("yt-card-body"):
                    ui.label(f"YapTracker {__version__}").classes("yt-meta")
                    rate, asked = CAPTURE.per_second(), CAPTURE.asked_fps  # really delivered (#187)
                    ui.label(
                        f"Capture: {rate:.1f} frames/s from Windows (asked for {asked:g})"
                        if rate is not None
                        else "Capture: not running right now"
                    ).classes("yt-meta").mark("capture-rate")
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
