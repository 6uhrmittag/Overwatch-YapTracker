"""Search (#30): "who said that thing about Rein?" Every yap ever read, newest first.

Words match what was said and who said it ("rein" also finds "reinhardt"); filters narrow it to
a channel, a yapper and a time span. A click on a result opens its match transcript (#29).
"""

import html
import time

from nicegui import ui

from yaptracker import runtime
from yaptracker.glyphs import GLYPH
from yaptracker.ui.components import count, switch
from yaptracker.ui.line_actions import delete_button
from yaptracker.ui.picker import LinePicker
from yaptracker.ui.snap_dialog import snap_dialog
from yaptracker.ui.yappers import matching

SHOWN = 100  # newest first; more words or a filter find older ones
_CHANNELS = {"": "All", "team": "Team", "match": "Match", "group": "Group", "system": "System"}
_SPANS = {"any": "Any time", "today": "Today", "week": "Last 7 days", "month": "Last 30 days"}
_NAMES = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}


def _since(span: str, now: float) -> float | None:
    if span == "any":
        return None
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    return midnight - {"today": 0, "week": 6, "month": 29}[span] * 86400


def marked_html(marked: str) -> str:
    """Escaped text with the found words highlighted and emoji/icons as a chip (#128)."""
    text = html.escape(marked, quote=False)
    text = text.replace("\x01", '<mark class="yt-hit">').replace("\x02", "</mark>")
    return text.replace(GLYPH, f'<span class="yt-glyph">{GLYPH}</span>')


def search() -> None:
    state = {"text": "", "who": "", "channel": "", "span": "any", "callouts": False}

    def open_snap(chosen: list) -> None:  # lines from search for a yap snap (#155)
        words = state["text"].strip()
        snap_dialog(chosen, f"From a search for \u201c{words}\u201d" if words else "From a search",
                    started_at=None)  # fmt: skip

    picker = LinePicker(open_snap)
    with ui.element("header").classes("yt-header"):
        ui.label("Search").classes("yt-h1")
        found = ui.label().classes("yt-meta").mark("search-count")
        ui.element("div").classes("yt-grow")
        picker.start_button()
    picker.bar()
    with ui.element("div").classes("yt-row yt-filters"):
        words = (
            ui.input(placeholder="What was said? e.g. rein")
            .props("dense borderless clearable debounce=250 autofocus")
            .classes("yt-search yt-grow")
            .mark("search-box")
        )
        who = (
            ui.input(placeholder="Who said it?")
            .props("dense borderless clearable debounce=250")
            .classes("yt-search yt-search--who")
            .mark("search-who")
        )
    with ui.element("div").classes("yt-row yt-filters"):
        channels = ui.element("div").classes("yt-seg").mark("search-channels")
        switch("Callouts", False, lambda on: choose("callouts", on)).mark("search-callouts")
        ui.element("div").classes("yt-grow")
        spans = ui.element("div").classes("yt-seg").mark("search-spans")
    with ui.element("section").classes("yt-card yt-card--list"):
        body = ui.element("div").classes("yt-card-body yt-transcript").mark("search-results")

    def segment(container, options: dict, key: str) -> None:
        container.clear()
        with container:
            for value, label in options.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"{key}-{value or 'all'}")
                if state[key] == value:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(label)
                item.on("click", lambda value=value: choose(key, value))

    def choose(key: str, value: str) -> None:
        state[key] = value
        render()

    def render() -> None:
        segment(channels, _CHANNELS, "channel")
        segment(spans, _SPANS, "span")
        body.clear()
        picker.clear_rows()
        found.set_text("")
        store = runtime.store
        if store is None:
            return
        player_ids = None
        if state["who"].strip():
            players = matching(store.players(), store.player_names(), state["who"])
            player_ids = [p.id for p in players]
        hits = store.find(
            state["text"],
            channel=state["channel"] or None,
            player_ids=player_ids,
            since=_since(state["span"], time.time()),
            callouts=state["callouts"],  # comms-wheel lines ("Enemy Sombra!"), off by default
            limit=SHOWN,
        )
        with body:
            if not state["text"].strip() and player_ids is None:
                ui.label("Type a word, a name, or both.").classes("yt-h2")
                ui.label(
                    "Searches everything ever read in chat. Half words work too: rein finds "
                    "Reinhardt."
                ).classes("yt-hint")
                return
            if not hits:
                ui.label("Nobody said that. Yet.").classes("yt-hint").mark("search-none")
                return
            for hit in hits:
                picker.add(hit.message, _result(hit, picker))
        found.set_text(
            f"newest {SHOWN} shown" if len(hits) == SHOWN else count(len(hits), "yap", "yaps")
        )

    def on_text(e) -> None:
        state["text"] = e.value or ""
        render()

    def on_who(e) -> None:
        state["who"] = e.value or ""
        render()

    words.on_value_change(on_text)
    who.on_value_change(on_who)
    render()


def _result(hit, picker: LinePicker) -> ui.element:
    """One found yap; a click opens its match, or picks it for a snap (#155)."""
    message = hit.message
    channel = message.channel if message.channel in _NAMES else "chat"
    row = ui.element("div").classes(f"yt-line yt-line--{channel} yt-result")
    row.mark(f"search-hit hit-{message.id}")

    def clicked(e) -> None:
        if picker.clicked(message, bool((e.args or {}).get("shiftKey"))):
            return
        if message.match_id is not None:
            ui.context.client.yt_show("sessions", session_id=hit.session_id,
                                      match_id=message.match_id)  # fmt: skip

    row.on("click", clicked, ["shiftKey"])
    with row:
        day = time.strftime("%a %b %d, %H:%M", time.localtime(message.ts)).replace(" 0", " ")
        ui.label(day).classes("yt-line-time yt-line-when")
        ui.label(_NAMES.get(channel, "Chat")).classes(f"yt-line-ch yt-ch-{channel}")
        who = message.speaker_raw if channel != "system" else ""
        who = "you" if who and message.role == "me" else who
        ui.label(f"{who}:" if who else "").classes(f"yt-line-name yt-ch-{channel}")
        ui.html(marked_html(hit.marked), sanitize=False).classes("yt-line-text")
        if hit.match_number:
            where = f"Match {hit.match_number}" + (f" on {hit.map.title()}" if hit.map else "")
            ui.label(where).classes("yt-meta yt-result-where")
    delete_button(row, lambda: [message.id])  # (#227)
    return row
