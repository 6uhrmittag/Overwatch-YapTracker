"""Sessions (#29): look back at last night. Evenings -> their matches -> the whole transcript.

Matches with a capture gap are marked incomplete, and the gap shows at its place in the
transcript ("Not recorded 21:04-21:10"), never as a silent hole (#75).
"""

import time

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui import icons
from yaptracker.ui.components import button, callout_toggle, count, when
from yaptracker.ui.heart import Heart
from yaptracker.ui.picker import LinePicker
from yaptracker.ui.snap_dialog import snap_dialog
from yaptracker.ui.views import (
    _OUTCOMES,
    _WHY,
    AGAIN_HINT,
    chat_line,
    fill_line,
    repeat,
    same_callout,
    show_picture,
)

_GAP_WHY = {
    **_WHY,
    "paused": "paused",
    "app_not_running": "YapTracker wasn't running",
    "deferred_lost": "kept to read after the match, lost when YapTracker closed",
}


def _clock(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _length(start: float, end: float) -> str:
    minutes = max(0, int((end - start) // 60))
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _match_end(match) -> float:
    return match.ended_at or match.last_yap or match.started_at


def sessions(session_id: int | None = None, match_id: int | None = None) -> None:
    """The list; with a session and match (a search result, #30) that transcript right away."""
    view = ui.element("div").classes("yt-view")

    def show_sessions() -> None:
        view.clear()
        with view:
            _session_list(show_session)

    def show_session(session) -> None:
        view.clear()
        with view:
            _match_list(session, show_sessions, lambda m, n: show_match(session, m, n))

    def show_match(session, match, number: int) -> None:
        view.clear()
        with view:
            _transcript(match, number, lambda: show_session(session))

    store = runtime.store
    session = next((r for r in store.sessions() if r.id == session_id), None) if store else None
    matches = store.session_matches(session_id) if session else []
    number = next((n for n, m in enumerate(matches, start=1) if m.id == match_id), None)
    if number is not None:
        show_match(session, matches[number - 1], number)
    else:
        show_sessions()


def _session_list(open_session) -> None:
    with ui.element("header").classes("yt-header"):
        ui.label("Sessions").classes("yt-h1")
    store = runtime.store
    rows = store.sessions() if store else []
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body").mark("sessions"):
            if not rows:
                ui.label("No sessions yet").classes("yt-h2")
                ui.label("Every evening of play lands here, match by match.").classes("yt-hint")
                return
            for session in rows:
                row = ui.element("div").classes("yt-yapper").mark(f"session session-{session.id}")
                row.on("click", lambda s=session: open_session(s))
                with row:
                    day = time.strftime("%A, %b %d", time.localtime(session.started_at))
                    ui.label(day.replace(" 0", " ")).classes("yt-yapper-name")
                    ui.label(f"{when(session.started_at)}").classes("yt-meta")
                    ui.element("div").classes("yt-grow")
                    span = f"{_clock(session.started_at)}\u2013{_clock(session.ended_at)}"
                    ui.label(
                        f"{span} \u00b7 {_length(session.started_at, session.ended_at)} \u00b7 "
                        f"{count(session.matches, 'match', 'matches')} \u00b7 "
                        f"{count(session.yaps, 'yap', 'yaps')}"
                    ).classes("yt-meta")


def _match_list(session, back, open_match) -> None:
    store = runtime.store
    with ui.element("header").classes("yt-header"):
        button("\u2190 All sessions", back, "quiet").mark("back-to-sessions")
        day = time.strftime("%A, %b %d", time.localtime(session.started_at)).replace(" 0", " ")
        ui.label(day).classes("yt-h1")
    ui.label("Open a match to read it back or make a yap snap.").classes("yt-hint").mark(
        "matches-hint"
    )  # snaps are in the match, in Search and in Live (#325)
    matches = store.session_matches(session.id)
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body").mark("matches"):
            if not matches:
                ui.label("No match in this session: YapTracker ran, nobody typed.").classes(
                    "yt-hint"
                )
            for number, match in enumerate(matches, start=1):
                row = ui.element("div").classes("yt-yapper").mark(f"match match-{match.id}")
                row.on("click", lambda m=match, n=number: open_match(m, n))
                with row:
                    ui.label(_title(match, number)).classes("yt-yapper-name")
                    if match.loved_at:  # hearted (#282)
                        ui.html(icons.HEART, sanitize=False).classes("yt-heart-mark").props(
                            'title="Loved"'
                        ).mark("loved")
                    if match.outcome:
                        ui.label(_OUTCOMES.get(match.outcome, match.outcome)).classes(
                            f"yt-outcome yt-outcome--{match.outcome}"
                        )
                    if store.gaps_between(match.started_at, _match_end(match)):
                        ui.label("incomplete").classes("yt-incomplete").mark("incomplete")
                    ui.element("div").classes("yt-grow")
                    mode = f"{match.mode.title()} \u00b7 " if match.mode else ""
                    ui.label(
                        f"{mode}{_clock(match.started_at)} \u00b7 "
                        f"{_length(match.started_at, _match_end(match))} \u00b7 "
                        f"{count(match.yaps, 'yap', 'yaps')}"
                    ).classes("yt-meta")


def _title(match, number: int) -> str:
    return f"Match {number}" + (f" on {match.map.title()}" if match.map else "")


def _read_again(match_id: int, rows: dict[int, dict]):
    """The match's "Read again, best quality" (#333): its progress line in words, better
    readings into their rows at once. Returns what the button does."""
    store = runtime.store
    progress = ui.label().classes("yt-hint yt-hidden").mark("read-again-progress")
    shown: set[int] = set()

    def start() -> None:
        if runtime.read_again is not None:
            runtime.read_again.match(match_id)
            follow()

    def follow() -> None:
        job = runtime.read_again.job(match_id) if runtime.read_again is not None else None
        if job is None:
            return
        for message_id in set(job.better) - shown:
            shown.add(message_id)
            if message_id in rows and (fresh := store.message(message_id)) is not None:
                fill_line(rows[message_id], fresh)
        lines, better = count(len(job.ids), "line", "lines"), f"{len(job.better)} better"
        if job.finished:
            text = f"Read {lines} again: {better}. {AGAIN_HINT}"
        elif runtime.matches is not None and runtime.matches.running:
            text = "A match is running: I read them again once it's over."
        else:
            text = f"Reading {lines} again\u2026 {better} so far."
        progress.set_text(text)
        progress.classes(remove="yt-hidden")

    ui.timer(1.0, follow)
    return start


def _transcript(match, number: int, back) -> None:
    store = runtime.store

    def open_snap(chosen: list) -> None:
        day = time.strftime("%a %b %d, %Y", time.localtime(match.started_at)).replace(" 0", " ")
        mode = f" \u00b7 {match.mode.title()}" if match.mode else ""
        snap_dialog(chosen, f"{_title(match, number)}{mode} \u00b7 {day}", match.started_at)

    picker = LinePicker(open_snap)
    with ui.element("header").classes("yt-header"):
        button("\u2190 All matches", back, "quiet").mark("back-to-matches")
        ui.label(_title(match, number)).classes("yt-h1")
        if match.outcome:
            ui.label(_OUTCOMES.get(match.outcome, match.outcome)).classes(
                f"yt-outcome yt-outcome--{match.outcome}"
            )
        Heart(lambda _: _title(match, number)).show(match.id)  # love it afterwards (#282)
        ui.element("div").classes("yt-grow")
        toggle_slot = ui.element("div")  # the Callouts switch (#289)
        again = button("Read again, best quality", lambda: read_again(), "quiet")
        again.mark("read-again").props(f'title="{AGAIN_HINT}"')
        picker.start_button()
    picker.bar()
    rows: dict[int, dict] = {}  # message id -> its row, so a channel fix shows at once (#283)
    read_again = _read_again(match.id, rows)

    def clicked(message, shift: bool) -> None:
        if not picker.clicked(message, shift):
            show_picture(message, rows.get(message.id))

    verdicts = {p.id: p.verdict for p in store.players()}
    messages = store.messages(match.id)
    gaps = store.gaps_between(match.started_at, _match_end(match))
    events = [(m.ts, "yap", m) for m in messages] + [(g[0], "gap", g) for g in gaps]
    if match.ended_at and any(m.ts > match.ended_at for m in messages):
        events.append((match.ended_at, "end", match))  # what was said after the result (#176)
    if any(m.ts < match.started_at for m in messages):
        events.append((match.started_at, "start", match))  # chat before it, e.g. the range (#307)
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body yt-transcript").mark("transcript") as body:
            if not events:
                ui.label("Nobody typed in this match. Suspiciously quiet lobby.").classes("yt-hint")
            last = None  # the row before, to count repeated callouts
            for _, kind, item in sorted(events, key=lambda e: (e[0], e[1] != "start")):
                if kind in ("start", "end", "gap"):
                    last = None  # never count repeats across a divider
                if kind == "start":
                    ui.label("The match starts").classes("yt-gap-line yt-end-line").mark(
                        "start-line"
                    )
                    continue
                if kind == "end":
                    result = (
                        f" ({_OUTCOMES.get(item.outcome, item.outcome)})" if item.outcome else ""
                    )
                    ui.label(f"After the match{result}").classes("yt-gap-line yt-end-line").mark(
                        "end-line"
                    )
                    continue
                if kind == "gap":
                    started, ended, reason = item
                    span = f"{_clock(started)}\u2013{_clock(ended)}" if ended else \
                        f"since {_clock(started)}"  # fmt: skip
                    ui.label(f"Not recorded {span} ({_GAP_WHY.get(reason, reason)})").classes(
                        "yt-gap-line"
                    ).mark("gap-line")
                elif last and same_callout(last[0], item):
                    repeat(last[1], item.id)  # "Enemy Sombra!" x4 (#185)
                    picker.add(item, last[1]["line"])
                else:
                    row = chat_line(item, match.started_at, verdicts.get(item.player_id),
                                    on_click=lambda shift, m=item: clicked(m, shift))  # fmt: skip
                    rows[item.id] = row
                    picker.add(item, row["line"])
                    last = (item, row)
    with toggle_slot:
        callout_toggle(body)(sum(1 for m in messages if m.hero))  # hidden by default (#289)
