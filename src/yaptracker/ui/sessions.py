"""Sessions (#29): look back at last night. Evenings -> their matches -> the whole transcript.

Matches with a capture gap are marked incomplete, and the gap shows at its place in the
transcript ("Not recorded 21:04-21:10"), never as a silent hole (#75).
"""

import time

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.components import button, count, when
from yaptracker.ui.picker import LinePicker
from yaptracker.ui.snap_dialog import snap_dialog
from yaptracker.ui.views import _OUTCOMES, _WHY, chat_line, show_picture

_GAP_WHY = {**_WHY, "paused": "paused", "app_not_running": "YapTracker wasn't running"}


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
        ui.element("div").classes("yt-grow")
        picker.start_button()
    picker.bar()

    def clicked(message, shift: bool) -> None:
        if not picker.clicked(message, shift):
            show_picture(message)

    verdicts = {p.id: p.verdict for p in store.players()}
    messages = store.messages(match.id)
    gaps = store.gaps_between(match.started_at, _match_end(match))
    events = [(m.ts, "yap", m) for m in messages] + [(g[0], "gap", g) for g in gaps]
    if match.ended_at and any(m.ts > match.ended_at for m in messages):
        events.append((match.ended_at, "end", match))  # what was said after the result (#176)
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body yt-transcript").mark("transcript"):
            if not events:
                ui.label("Nobody typed in this match. Suspiciously quiet lobby.").classes("yt-hint")
            for _, kind, item in sorted(events, key=lambda e: e[0]):
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
                else:
                    row = chat_line(item, match.started_at, verdicts.get(item.player_id),
                                    on_click=lambda shift, m=item: clicked(m, shift))  # fmt: skip
                    picker.add(item, row["line"])
