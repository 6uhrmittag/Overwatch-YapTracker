"""Quick verdicts (#220): one click in the Yappers list, or from a name in the chat, without
opening the profile. Every change says Saved and can be undone for a few seconds, because a
misclick at the end of a match is easy."""

from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.ui.components import VERDICTS, button, saved_chip

UNDO_S = 5.0
# Clicks here are the button's own: the row underneath doesn't open the profile.
_OWN_CLICK = "(e) => { e.stopPropagation(); emit(); }"
# A click that ends a text selection isn't a click on the name (#221).
_CLICK_NOT_DRAG = "(e) => { e.stopPropagation(); if (window.getSelection().isCollapsed) emit(); }"


class UndoBar:
    """'Saved · Pickle: Bestie · Undo' at the bottom of the window, for a few seconds."""

    def __init__(self) -> None:
        with ui.element("div").classes("yt-undo yt-hidden").mark("undo-bar") as self._bar:
            saved_chip()
            self._text = ui.label().classes("yt-undo-text").mark("undo-text")
            button("Undo", self._undo, variant="quiet").mark("undo")
        self._on_undo: Callable[[], None] | None = None
        self._shown = 0  # a newer message outlives the timer of an older one

    def show(self, text: str, on_undo: Callable[[], None]) -> None:
        self._shown += 1
        shown, self._on_undo = self._shown, on_undo
        self._text.set_text(text)
        self._bar.classes(remove="yt-hidden")
        with self._bar:
            ui.timer(UNDO_S, lambda: self._hide(shown), once=True)

    def _hide(self, shown: int) -> None:
        if shown == self._shown:
            self._bar.classes(add="yt-hidden")
            self._on_undo = None

    def _undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo()
        self._hide(self._shown)


def _bar() -> UndoBar | None:
    return getattr(ui.context.client, "yt_undo", None)


def set_verdict(player_id: int, value: str, after: Callable[[], None]) -> None:
    """Clicking the current verdict again takes it back, as on the profile."""
    store, bar = runtime.store, _bar()  # the bar first: after() deletes the clicked button
    player = store.player(player_id)
    old = player.verdict
    new = None if value == old else value
    store.set_verdict(player_id, new)
    after()

    def undo() -> None:
        store.set_verdict(player_id, old)
        after()

    if bar is not None:
        bar.show(f"{player.display_name}: {VERDICTS[new][0] if new else 'no verdict yet'}", undo)


def add_note(player_id: int, note: str) -> None:
    """A quick note goes below what's already written."""
    note = note.strip()
    store, bar = runtime.store, _bar()
    if not note or store is None:
        return
    player = store.player(player_id)
    old = player.notes or ""
    store.set_notes(player_id, f"{old.rstrip()}\n{note}" if old.strip() else note)
    if bar is not None:
        bar.show(f"Note added for {player.display_name}", lambda: store.set_notes(player_id, old))


def quick_buttons(current: str | None, on_pick: Callable[[str], None]) -> ui.element:
    """The four stickers, small: dimmed, full colour on hover and for the current verdict."""
    with ui.element("div").classes("yt-quick").mark("quick-verdicts") as row:
        for value, (label, _) in VERDICTS.items():
            on = value == current
            b = ui.element("button").classes(f"yt-quick-v yt-quick-v--{value}")
            b.props(f'type="button" aria-pressed="{str(on).lower()}"').mark(f"quick-{value}")
            if on:
                b.classes(add="is-on")
            with b:
                ui.label(label)
            b.on("click", lambda value=value: on_pick(value), js_handler=_OWN_CLICK)
    return row


def who_menu(anchor: ui.element, player_id: int) -> None:
    """A name in the chat was clicked: verdict, a quick note, Open profile."""
    store = runtime.store
    player = store.player(player_id) if store else None
    if player is None:
        return
    client = ui.context.client  # kept: the menu deletes itself when it closes
    with anchor:
        menu = ui.menu().classes("yt-who").mark("who-menu")
    with menu, ui.element("div").classes("yt-who-body"):
        ui.label(player.display_name).classes("yt-who-name")
        stickers = ui.element("div")
        note = ui.input(placeholder="Quick note, Enter saves").props("dense borderless")
        note.classes("yt-who-note").mark("who-note")
        button("Open profile", lambda: open_profile(), variant="quiet").mark("who-profile")

    def render() -> None:
        stickers.clear()
        with stickers:
            quick_buttons(store.player(player_id).verdict,
                          lambda v: set_verdict(player_id, v, render))  # fmt: skip

    def save_note() -> None:
        add_note(player_id, note.value or "")
        note.set_value("")

    def open_profile() -> None:
        save_note()
        client.yt_show("yappers", player_id=player_id)  # replaces Live, menu and all

    note.on("keydown.enter", save_note)
    menu.on_value_change(lambda e: None if e.value else (save_note(), menu.delete()))
    render()
    menu.open()


def clickable_name(name: ui.element, message) -> None:
    """Names of other players in Live and transcripts open the menu; not you, crew or system."""
    if message.player_id is None or message.role in ("me", "crew") or message.channel == "system":
        return
    name.classes(add="yt-line-name--who").props('title="Verdict, note, profile"')
    name.on("click", lambda: who_menu(name, message.player_id), js_handler=_CLICK_NOT_DRAG)
