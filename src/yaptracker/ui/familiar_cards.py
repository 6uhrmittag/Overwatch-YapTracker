""" "Look who's back!" in Live (#26, #518): one slim strip above the chat, a chip per familiar face.

The strip never changes its height (empty, it says what will show up), so the chat never moves;
loud by colour and one pulse, not by size. Chips stay for the match and clear themselves when
the next one starts: nothing to click in a match. A chip opens the full card as a popover
(Esc or a click outside closes it). Nope players get a red chip in the same strip.
"""

from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.familiar import Card
from yaptracker.ui import backlog
from yaptracker.ui.components import button, count, spicy_mark, sticker, when

CHIPS = 3  # more than fit -> a "+N" chip with the rest
EMPTY = "Familiar faces show up here."


class FacesStrip:
    """The strip; show(cards) redraws it when the faces change."""

    def __init__(self, on_open: Callable[[int], None]) -> None:
        self._on_open = on_open
        self._shown: list[tuple[int, float]] | None = None
        self._ids: set[int] = set()
        with ui.element("div").classes("yt-strip").mark("faces") as self.element:
            ui.label("Look who's back!").classes("yt-strip-label")
            self._chips = ui.element("div").classes("yt-strip-chips")

    def show(self, cards: list[Card]) -> None:
        key = [(c.player_id, c.shown_at) for c in cards]
        if key == self._shown:
            return
        self._shown = key
        new = {c.player_id for c in cards} - self._ids
        self._ids = {c.player_id for c in cards}
        self._chips.clear()
        with self._chips:
            if not cards:
                ui.label(EMPTY).classes("yt-strip-empty").mark("faces-empty")
            for card in cards[:CHIPS]:
                self._chip(card, card.player_id in new)
            rest = cards[CHIPS:]
            if rest:
                more = ui.element("button").classes("yt-face-chip yt-face-chip--more")
                more.props(f'type="button" aria-label="{len(rest)} more familiar faces"')
                with more.mark("faces-more"):
                    ui.label(f"+{len(rest)}")
                    with popover(more):
                        for card in rest:
                            face_card(card, lambda pid=card.player_id: self._on_open(pid))

    def _chip(self, card: Card, new: bool) -> None:
        kind = " yt-face-chip--avoid" if card.verdict == "avoid" else ""
        pulse = " yt-face-chip--new" if new else ""
        chip = ui.element("button").classes(f"yt-face-chip{kind}{pulse}").props('type="button"')
        with chip.mark("face-avoid-chip" if kind else "face-chip"):
            ui.label(card.name).classes("yt-face-chip-name")
            if card.verdict:
                sticker(card.verdict).classes("yt-sticker--mini")
            ui.label(f"last seen {when(card.last_met)}").classes("yt-face-chip-meta")
            if card.note:
                ui.label(f"“{card.note}”").classes("yt-face-chip-meta yt-face-chip-note")
            with popover(chip):
                face_card(card, lambda: self._on_open(card.player_id))


def popover(anchor: ui.element | None) -> ui.menu:
    """The full card under a chip or a name mark (#519); Esc or a click outside closes it
    (Quasar's menu). anchor: opens on its click; None: the caller opens it."""
    menu = ui.menu().props("no-parent-event anchor='bottom left' self='top left'")
    menu.classes("yt-face-pop").mark("face-pop")
    if anchor is not None:
        anchor.on("click", menu.open)
    return menu


def face_card(card: Card, on_open: Callable[[], None]) -> None:
    """The full card: everything you know, "Open profile". Nope players: a red heads-up."""
    met = f"Last seen {when(card.last_met)}"
    if card.verdict == "avoid":  # heads-up, not a welcome
        with ui.element("article").classes("yt-face yt-face--avoid").mark("face-avoid") as face:
            with ui.element("div").classes("yt-grow"):
                ui.label(card.name).classes("yt-face-name yt-face-name--small")
                ui.label(f"{met} · “{card.note}”" if card.note else met).classes("yt-meta")
            sticker("avoid")
        face.on("click", on_open)
        return
    with ui.element("article").classes("yt-face").mark("face"):
        banner = "Look who was there!" if card.after else "Look who's back!"  # (#335)
        ui.label(banner).classes("yt-face-banner")
        with ui.element("div").classes("yt-face-body"):
            with ui.element("div").classes("yt-row"):
                ui.label(card.name).classes("yt-face-name")
                if card.verdict:
                    sticker(card.verdict)
            together = count(card.matches, "match", "matches")
            with ui.element("div").classes("yt-row yt-row--wrap"):
                ui.label(f"{met} · {together} together · "
                         f"{count(card.yaps, 'yap', 'yaps')}").classes("yt-face-meta")  # fmt: skip
                if card.match_id is not None:  # its match still being read: not final (#502)
                    backlog.follow({card.match_id: backlog.badge_label()}, backlog.badge)
            if card.note:
                ui.label(f"“{card.note}”").classes("yt-face-note")
            if card.spicy:
                _heads_up(card)
            with ui.element("div").classes("yt-row"):
                button("Open profile", on_open, "primary").mark("face-open")


def _heads_up(card: Card) -> None:
    """Spicy history (#77): an orange heads-up and a suggestion. Never a verdict by itself."""
    with ui.element("div").classes("yt-row yt-heads-up").mark("face-heads-up"):
        spicy_mark()
        ui.label(f"Heads-up: last time {count(card.spicy, 'spicy yap', 'spicy yaps')}")
        ui.element("div").classes("yt-grow")
        if card.verdict != "avoid":
            nope = button("Set verdict: Nope?", lambda: suggest_nope(), "quiet")
            nope.mark("face-nope")

    def suggest_nope() -> None:
        runtime.store.set_verdict(card.player_id, "avoid")
        nope.set_visibility(False)
