"""A yapper's profile (#25, docs/ui/mockup/Profile): your verdict in one click, notes that save
themselves, how often you met, and everything they said, grouped by match."""

import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.components import VERDICTS, button, count, saved_chip, when

# Yap-o-meter: yaps per match together.
_LEVELS = [(1, "Silent type"), (3, "Casual yapper"), (8, "Certified yapper"),
           (float("inf"), "Yap lord")]  # fmt: skip
_CHANNELS = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}


def yap_level(yaps: int, matches: int) -> tuple[str, float]:
    """(label, bar fill 0..1) from how much they say per match."""
    per_match = yaps / max(1, matches)
    label = next(name for limit, name in _LEVELS if per_match < limit)
    return label, min(1.0, max(0.04, per_match / 10))


def profile(player_id: int, on_back: Callable[[], None]) -> None:
    store = runtime.store
    player = store.player(player_id) if store else None
    if player is None:
        on_back()
        return
    with ui.element("div").classes("yt-columns yt-profile"):
        with ui.element("div").classes("yt-profile-main"):
            button("\u2190 All yappers", on_back, "quiet").mark("back-to-yappers")
            ui.label(player.display_name).classes("yt-profile-name")
            aliases = store.aliases(player_id)
            if aliases:
                ui.label("Also read as " + ", ".join(aliases)).classes("yt-hint")
            ui.label("Your verdict").classes("yt-h2")
            verdicts = ui.element("div").classes("yt-row").mark("verdicts")
            tiles = [
                (player.matches, "matches together"),
                (player.yaps, "yaps"),
                (_day(player.first_seen), "first met"),
                (when(player.last_seen).capitalize(), "last seen"),
            ]
            with ui.element("div").classes("yt-tiles"):
                for value, label in tiles:
                    with ui.element("div").classes("yt-tile"):
                        ui.label(str(value)).classes("yt-tile-value")
                        ui.label(label).classes("yt-meta")
            level, fill = yap_level(player.yaps, player.matches)
            with ui.element("div").classes("yt-row"):
                ui.label("Yap-o-meter").classes("yt-h2")
                ui.label(level).classes("yt-meter-level").mark("yap-level")
            with ui.element("div").classes("yt-meter"):
                ui.element("div").classes("yt-meter-fill").style(f"width: {fill:.0%}")
            with ui.element("div").classes("yt-meter-scale"):
                for _, name in _LEVELS:
                    ui.label(name)
            with ui.element("div").classes("yt-row"):
                ui.label("Notes").classes("yt-h2")
                saved = ui.element("span").classes("yt-hidden")
                with saved:
                    saved_chip()
            notes = (
                ui.textarea(
                    value=player.notes,
                    placeholder="What do you want to remember? "
                    "\u201cHype L\u00facio, greet with a wahoo.\u201d",
                )  # fmt: skip
                .props("borderless autogrow debounce=600")
                .classes("yt-notes")
                .mark("notes")
            )
            ui.label("Saves by itself. Shows up on their card when they're back.").classes(
                "yt-hint"
            )
        with ui.element("aside").classes("yt-card yt-profile-yaps"):
            with ui.element("div").classes("yt-card-body"):
                ui.label("Their greatest yaps").classes("yt-h2")
                _yaps(player_id)

    def render_verdicts(current: str | None) -> None:
        verdicts.clear()
        with verdicts:
            for value, (label, _) in VERDICTS.items():
                on = value == current
                b = ui.element("button").classes(f"yt-verdict yt-verdict--{value}")
                b.props(f'type="button" aria-pressed="{str(on).lower()}"').mark(f"verdict-{value}")
                if on:
                    b.classes(add="is-on")
                with b:
                    ui.element("span").classes("yt-verdict-dot")
                    ui.label(label)
                b.on("click", lambda value=value: pick(value))

    def pick(value: str) -> None:
        current = store.player(player_id).verdict
        new = None if value == current else value  # clicking it again takes it back
        store.set_verdict(player_id, new)
        render_verdicts(new)

    def save_notes(e) -> None:
        store.set_notes(player_id, e.value or "")
        saved.classes(remove="yt-hidden")

    notes.on_value_change(save_notes)
    render_verdicts(player.verdict)


def _day(ts: float | None) -> str:
    return time.strftime("%b %d", time.localtime(ts)).replace(" 0", " ") if ts else "-"


def _yaps(player_id: int) -> None:
    store = runtime.store
    messages = store.player_messages(player_id)
    if not messages:
        ui.label("They haven't said anything yet. Strong silent type.").classes("yt-hint")
        return
    by_match: dict[int | None, list] = {}
    for message in messages:
        by_match.setdefault(message.match_id, []).append(message)
    for match_id, said in by_match.items():
        started = store.match_started(match_id) if match_id else None
        day = time.strftime("%a, %b %d", time.localtime(started or said[0].ts)).replace(" 0", " ")
        title = f"{day} \u00b7 Match {store.match_number(match_id)}" if match_id else day
        ui.label(title).classes("yt-match-title")
        for message in reversed(said):  # in the order they said it
            channel = message.channel if message.channel in _CHANNELS else "chat"
            with ui.element("div").classes("yt-their-yap"):
                ui.label(_CHANNELS.get(channel, "Chat")).classes(f"yt-line-ch yt-ch-{channel}")
                ui.label(message.text).classes("yt-line-text")
    ui.label(count(len(messages), "yap", "yaps") + " in total").classes("yt-meta")
