"""The "Look who's back!" cards in Live (#26, docs/ui/mockup/Live): the loudest thing in the app,
so it can't be missed on a second monitor. Nope players get a compact red card instead."""

from collections.abc import Callable

from nicegui import ui

from yaptracker.familiar import Card
from yaptracker.ui.components import button, count, sticker, when


def familiar_card(card: Card, on_open: Callable[[], None], on_dismiss: Callable[[], None]) -> None:
    met = f"Last seen {when(card.last_met)}"
    if card.verdict == "avoid":  # heads-up, not a welcome
        with ui.element("article").classes("yt-face yt-face--avoid").mark("face-avoid") as face:
            with ui.element("div").classes("yt-grow"):
                ui.label(card.name).classes("yt-face-name yt-face-name--small")
                ui.label(f"{met} \u00b7 \u201c{card.note}\u201d" if card.note else met).classes(
                    "yt-meta"
                )
            sticker("avoid")
        face.on("click", on_open)
        return
    with ui.element("article").classes("yt-face").mark("face"):
        ui.label("Look who's back!").classes("yt-face-banner")
        with ui.element("div").classes("yt-face-body"):
            with ui.element("div").classes("yt-row"):
                ui.label(card.name).classes("yt-face-name")
                if card.verdict:
                    sticker(card.verdict)
            together = count(card.matches, "match", "matches")
            ui.label(f"{met} \u00b7 {together} together \u00b7 "
                     f"{count(card.yaps, 'yap', 'yaps')}").classes("yt-face-meta")  # fmt: skip
            if card.note:
                ui.label(f"\u201c{card.note}\u201d").classes("yt-face-note")
            with ui.element("div").classes("yt-row"):
                button("Open profile", on_open, "primary").mark("face-open")
                button("Got it", on_dismiss).mark("face-ok")
