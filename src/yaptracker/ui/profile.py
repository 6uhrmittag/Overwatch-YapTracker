"""A yapper's profile (#25, docs/ui/mockup/Profile): your verdict in one click, notes that save
themselves, how often you met, and everything they said, grouped by match."""

import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.components import VERDICTS, button, count, saved_chip, spicy_mark, when

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
            with ui.element("div").classes("yt-row"):
                if aliases:
                    ui.label("Also read as " + ", ".join(aliases)).classes("yt-hint")
                button(
                    "Same person as someone else? Merge into\u2026",
                    lambda: _merge_dialog(player_id, player.display_name),
                    "quiet",
                ).mark("merge")
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
            if player.spicy:  # a heads-up, never a verdict (#77)
                with ui.element("div").classes("yt-row yt-heads-up").mark("spicy-count"):
                    spicy_mark()
                    ui.label(
                        f"{count(player.spicy, 'spicy yap', 'spicy yaps')}: flagged by Overwatch "
                        "or by you. Your call what that means."
                    )
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


def _merge_dialog(player_id: int, name: str) -> None:
    """OCR made two players of one person (#28): pick the other one, confirm, done."""
    from yaptracker import paths
    from yaptracker.store.backups import before_merge
    from yaptracker.ui.yappers import matching

    store = runtime.store
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-merge"):
        body = ui.element("div").classes("yt-card-body")

    def pick() -> None:
        body.clear()
        with body:
            ui.label(f"Merge {name} into\u2026").classes("yt-h2")
            box = ui.input(placeholder="The name to keep").props("dense borderless autofocus")
            box.classes("yt-lookup-box").mark("merge-search")
            results = ui.element("div").classes("yt-lookup-results")

            def search(e) -> None:
                results.clear()
                others = [p for p in store.players() if p.id != player_id]
                with results:
                    for other in matching(others, store.player_names(), e.value or "")[:6]:
                        row = ui.element("div").classes("yt-lookup-row").mark("merge-pick")
                        row.on("click", lambda o=other: confirm(o.id, o.display_name))
                        with row:
                            ui.label(other.display_name).classes("yt-lookup-name")

            box.on_value_change(search)

    def confirm(target_id: int, target: str) -> None:
        body.clear()
        with body:
            ui.label(f"{name} \u2192 {target}?").classes("yt-h2")
            ui.label(
                f"Their yaps, notes and spellings move over to {target}; {name} is gone "
                "afterwards. A backup is made first, so this can be undone."
            ).classes("yt-hint")
            with ui.element("div").classes("yt-actions"):
                button("Back", pick, "quiet")
                button(f"Merge into {target}", lambda: merge(target_id), "primary").mark("merge-ok")

    def merge(target_id: int) -> None:
        before_merge(store.backup_to, paths.backup_dir())
        store.merge_players(player_id, target_id)
        if runtime.players is not None:
            runtime.players.reload()
        client = ui.context.client  # before closing: a closed dialog deletes itself
        dialog.close()
        client.yt_show("yappers", player_id=target_id)

    pick()
    dialog.on_value_change(lambda e: None if e.value else dialog.delete())  # gone once closed
    dialog.open()


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
                if message.flagged:
                    spicy_mark()
    ui.label(count(len(messages), "yap", "yaps") + " in total").classes("yt-meta")
