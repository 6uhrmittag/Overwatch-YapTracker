"""Sessions (#29): look back at last night. Days -> their matches -> the whole transcript.

The list groups by day (#440), a day runs until 05:00; the sessions table stays behind the scenes.
Matches with a capture gap are marked incomplete, and the gap shows at its place in the
transcript ("Not recorded 21:04-21:10"), never as a silent hole (#75).
"Loved only" (#286) narrows days and matches to the hearted ones; numbers stay the day's.
"""

import time

from nicegui import ui

from yaptracker import config, days, runtime
from yaptracker.days import end_of as _match_end
from yaptracker.ui import backlog, icons
from yaptracker.ui.components import (
    button,
    callout_toggle,
    count,
    match_queue,
    place_name,
    sub_page,
    when,
)
from yaptracker.ui.heart import Heart
from yaptracker.ui.name_marks import NameMarks
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
_SHOW = {False: "Every match", True: "Loved only"}  # (#286); "All matches" is the way back


def _clock(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _length(start: float, end: float) -> str:
    return days.length(end - start)


def sessions(match_id: int | None = None, line_id: int | None = None) -> None:
    """The days list; with a match (a search result, #30) its transcript in its day right away,
    with a line (a profile's match heading, #388) scrolled to it."""
    view = ui.element("div").classes("yt-view")
    state = {"loved": False}  # "Loved only" (#286): kept while you go through days and matches
    listed = {"again": None}  # draws the list that's showing again; None in a transcript

    def hearted() -> None:
        """An Undo clicked after leaving the transcript: the list behind it is up to date."""
        if listed["again"] is not None:
            listed["again"]()

    def show_days() -> None:
        listed["again"] = show_days
        sub_page(None)
        view.clear()
        with view:
            _day_list(show_day, state, show_days)

    def show_day(key: str) -> None:
        listed["again"] = lambda: show_day(key)
        sub_page(show_days)  # the Sessions icon goes back to the list (#404)
        view.clear()
        with view:
            _match_list(key, show_days, lambda m, n: show_match(key, m, n), state,
                        lambda: show_day(key))  # fmt: skip

    def show_match(key: str, match, number: int, line: int | None = None) -> None:
        listed["again"] = None
        sub_page(show_days)
        view.clear()
        with view:
            _transcript(match, number, lambda: show_day(key), line, hearted)

    store = runtime.store
    key = store.match_day(match_id) if store and match_id is not None else None
    matches = store.played_matches(key, _reading()) if key else []
    number = next((n for n, m in enumerate(matches, start=1) if m.id == match_id), None)
    if number is not None:
        show_match(key, matches[number - 1], number, line_id)
    else:
        show_days()


def _reading() -> list[int]:
    """Matches whose chat still waits to be read: listed even before their first yap (#501)."""
    waiting = backlog.now()
    return [m for m in waiting.matches if m is not None] if waiting else []


def _loved_filter(state: dict, redraw) -> None:
    """Every match / Loved only (#286): the segments of Yappers and Search."""

    def choose(on: bool) -> None:
        state["loved"] = on
        redraw()

    with ui.element("div").classes("yt-row yt-filters"):
        with ui.element("div").classes("yt-seg").mark("loved-filter"):
            for on, label in _SHOW.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark("show-loved" if on else "show-all")
                if state["loved"] == on:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(label)
                item.on("click", lambda on=on: choose(on))


def _day_list(open_day, state: dict, redraw) -> None:
    with ui.element("header").classes("yt-header"):
        ui.label("Sessions").classes("yt-h1")
    ui.label(
        "One row per day you played. Past midnight still counts to the day before, until 5 am."
    ).classes("yt-hint").mark("days-hint")
    store = runtime.store
    rows = days.group(store.played_matches(also=_reading())) if store else []
    if rows:  # nothing to narrow before the first session
        _loved_filter(state, redraw)
    loved = {day.key: sum(1 for m in day.matches if m.loved_at) for day in rows}
    badges = {}
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body").mark("sessions"):
            if not rows:
                ui.label("No sessions yet").classes("yt-h2")
                ui.label("Every day you play lands here, match by match.").classes("yt-hint")
                return
            if state["loved"] and not any(loved.values()):
                ui.label("No loved matches yet").classes("yt-h2")
                ui.label(
                    "Click the heart on a match, in Live or at the top of its transcript, "
                    "and its day shows up here."
                ).classes("yt-hint").mark("no-loved")
                return
            for day in rows:
                if state["loved"] and not loved[day.key]:
                    continue
                row = ui.element("div").classes("yt-yapper").mark(f"day day-{day.key}")
                row.on("click", lambda k=day.key: open_day(k))
                with row:
                    ui.label(days.title(day.key)).classes("yt-yapper-name")
                    ui.label(when(*days.ago(day.key))).classes("yt-meta")
                    badges[tuple(m.id for m in day.matches)] = _badge()
                    ui.element("div").classes("yt-grow")
                    span = f"{_clock(day.started_at)}\u2013{_clock(day.ended_at)}"
                    matches = count(len(day.matches), "match", "matches")
                    if state["loved"]:  # the day's numbers would look like the loved ones'
                        ui.label(f"{loved[day.key]} loved of {matches}").classes("yt-meta")
                        continue
                    ui.label(
                        f"{span} \u00b7 {_length(0, day.played_s)} played \u00b7 "
                        f"{matches} \u00b7 {count(day.yaps, 'yap', 'yaps')}"
                    ).classes("yt-meta")
    backlog.follow(badges, backlog.day_badge)


def _badge() -> ui.label:
    """'Still reading', pulsing until the match's chat is read through (#501)."""
    return backlog.badge_label()


def _match_list(key: str, back, open_match, state: dict, redraw) -> None:
    store = runtime.store
    with ui.element("header").classes("yt-header"):
        button("\u2190 All days", back, "quiet").mark("back-to-sessions")
        ui.label(days.title(key)).classes("yt-h1")
    ui.label("Open a match to read it back or make a yap snap.").classes("yt-hint").mark(
        "matches-hint"
    )  # snaps are in the match, in Search and in Live (#325)
    blocks = days.blocks(store.played_matches(key, _reading()))
    only = state["loved"]
    if blocks:
        _loved_filter(state, redraw)
    badges = {}
    with ui.element("section").classes("yt-card yt-card--list"):
        with ui.element("div").classes("yt-card-body").mark("matches"):
            if not blocks:
                ui.label(
                    "No match left on this day: a match shows here once it has a yap or a result."
                ).classes("yt-hint")
            elif only and not any(m.loved_at for _, block in blocks for m in block):
                ui.label("No loved match on this day. Every match shows the others.").classes(
                    "yt-hint"
                ).mark("no-loved")
            number = 0
            for i, (pause, block) in enumerate(blocks):
                if i and not only:  # a quiet divider between play blocks (#440)
                    ui.label(f"Break, {_length(0, pause)}").classes("yt-break-line").mark(
                        "break-line"
                    )
                for match in block:
                    number += 1  # the day's number, also with Loved only (#286)
                    if only and not match.loved_at:
                        continue
                    badges[match.id] = _match_row(match, number, open_match)
    backlog.follow(badges, backlog.badge)


def _match_row(match, number: int, open_match) -> ui.label:
    store = runtime.store
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
        badge = _badge()
        ui.element("div").classes("yt-grow")
        mode = f"{match_queue(match)} \u00b7 " if match.mode else ""
        ui.label(
            f"{mode}{_clock(match.started_at)} \u00b7 "
            f"{_length(match.started_at, _match_end(match))} \u00b7 "
            f"{count(match.yaps, 'yap', 'yaps')}"
        ).classes("yt-meta")
    return badge


def _title(match, number: int) -> str:
    return f"Match {number}" + (f" on {place_name(match.map)}" if match.map else "")


def _no_read_again(match_id: int) -> str | None:
    """Why there's nothing to read again in this match, in words (#357); None if there is."""
    if runtime.read_again is None:
        return None
    if not config.line_pictures():
        return "Line pictures are off (Settings), so there's nothing to read again from."
    if not runtime.read_again.readable(match_id):
        return "No line pictures left for this match (or you fixed every line by hand)."
    return None


def _read_again(match_id: int, rows: dict[int, dict], button):
    """The match's "Read again, best quality" (#333): its progress line in words, better
    readings into their rows at once. Returns what the button does."""
    store = runtime.store
    progress = ui.label().classes("yt-hint yt-hidden").mark("read-again-progress")
    shown: set[int] = set()
    why = _no_read_again(match_id)
    if why:  # disabled with a reason, never a run that reads nothing (#357)
        button.props(f'disabled title="{why}"')
        progress.set_text(why)
        progress.classes(remove="yt-hidden")
        return lambda: None

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
        elif (waiting := runtime.read_again.waiting("them")) is not None:
            text = waiting
        else:
            text = f"Reading {lines} again\u2026 {better} so far."
        progress.set_text(text)
        progress.classes(remove="yt-hidden")

    ui.timer(1.0, follow)
    return start


def _transcript(match, number: int, back, line_id: int | None = None,
                hearted=lambda: None) -> None:  # fmt: skip
    store = runtime.store

    def open_snap(chosen: list) -> None:
        day = days.title(match.day or days.day_of(match.started_at), "%a %b %d, %Y")  # (#440)
        mode = f" \u00b7 {match_queue(match)}" if match.mode else ""
        snap_dialog(chosen, f"{_title(match, number)}{mode} \u00b7 {day}", match.started_at)

    picker = LinePicker(open_snap)
    with ui.element("header").classes("yt-header"):
        button("\u2190 All matches", back, "quiet").mark("back-to-matches")
        ui.label(_title(match, number)).classes("yt-h1")
        if match.outcome:
            ui.label(_OUTCOMES.get(match.outcome, match.outcome)).classes(
                f"yt-outcome yt-outcome--{match.outcome}"
            )
        Heart(lambda _: _title(match, number), hearted).show(match.id)  # love it afterwards (#282)
        ui.element("div").classes("yt-grow")
        toggle_slot = ui.element("div")  # the Callouts switch (#289)
        again = button("Read again, best quality", lambda: read_again(), "quiet")
        again.mark("read-again").props(f'title="{AGAIN_HINT}"')
        picker.start_button()
    picker.bar()
    rows: dict[int, dict] = {}  # message id -> its row, so a channel fix shows at once (#283)
    read_again = _read_again(match.id, rows, again)

    def clicked(message, shift: bool) -> None:
        if not picker.clicked(message, shift):
            show_picture(message, rows.get(message.id))

    with ui.element("div").classes("yt-reading-banner yt-hidden").mark("reading-banner") as banner:
        banner_text = ui.label().mark("reading-banner-text")
        with ui.element("div").classes("yt-meter"):
            done = ui.element("div").classes("yt-meter-fill")
    with ui.element("section").classes("yt-card yt-card--list"):
        body = ui.element("div").classes("yt-card-body yt-transcript").mark("transcript")
    with toggle_slot:
        callouts = callout_toggle(body)  # hidden by default (#289)
    shown = {"lines": _draw(match, body, rows, picker, clicked, callouts), "read": None}

    def follow() -> None:
        """While the match's chat is read after it (#501): the banner, and new lines at once."""
        said = backlog.banner(backlog.now(), match.id)
        banner.classes(**{"add" if said is None else "remove": "yt-hidden"})
        if said is not None:
            banner_text.set_text(said[0])
            done.style(f"width: {said[1]:.0%}")
        read = said and said[1]
        if read != shown["read"]:  # its last picture read, too: better readings show
            shown["read"] = read
            if len(lines := store.messages(match.id)) != shown["lines"] or said is None:
                shown["lines"] = _draw(match, body, rows, picker, clicked, callouts, lines)

    follow()
    ui.timer(backlog.FOLLOW_S, follow)
    if line_id is not None and line_id in rows:
        _point_at(rows[line_id]["line"])


def _point_at(line: ui.element) -> None:
    """The line you came for (#388): marked, and scrolled into the middle once it's drawn."""
    line.classes(add="yt-line--found")
    js = f"getHtmlElement({line.id})?.scrollIntoView({{block: 'center'}})"
    ui.timer(0.1, lambda: ui.run_javascript(js), once=True)


def _draw(match, body, rows: dict, picker, clicked, callouts, messages=None) -> int:
    """The transcript's lines, gaps and dividers into body (again); returns how many lines."""
    store = runtime.store
    body.clear()
    rows.clear()  # the same dict: Read again fills its rows in place
    picker.clear_rows()
    verdicts = {p.id: p.verdict for p in store.players()}
    messages = store.messages(match.id) if messages is None else messages
    marks = NameMarks(match.id, messages)  # a verdict mark on known names (#519)
    gaps = store.gaps_between(match.started_at, _match_end(match))
    events = [(m.ts, "yap", m) for m in messages] + [(g[0], "gap", g) for g in gaps]
    if match.ended_at and any(m.ts > match.ended_at for m in messages):
        events.append((match.ended_at, "end", match))  # what was said after the result (#176)
    if any(m.ts < match.started_at for m in messages):
        events.append((match.started_at, "start", match))  # chat before it, e.g. the range (#307)
    with body:
        if not events:
            ui.label("No yaps in this match. Suspiciously quiet lobby.").classes("yt-hint")
        last = None  # the row before, to count repeated callouts
        for _, kind, item in sorted(events, key=lambda e: (e[0], e[1] != "start")):
            if kind in ("start", "end", "gap"):
                last = None  # never count repeats across a divider
            if kind == "start":
                ui.label("The match starts").classes("yt-gap-line yt-end-line").mark("start-line")
                continue
            if kind == "end":
                result = f" ({_OUTCOMES.get(item.outcome, item.outcome)})" if item.outcome else ""
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
                                on_click=lambda shift, m=item: clicked(m, shift),
                                marks=marks)  # fmt: skip
                rows[item.id] = row
                picker.add(item, row["line"])
                last = (item, row)
    callouts(sum(1 for m in messages if m.hero))
    return len(messages)
