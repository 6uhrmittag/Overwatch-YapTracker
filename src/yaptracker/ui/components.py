"""Shared building blocks from the style kit (docs/ui/mockup/Kit.dc.html)."""

from collections.abc import Callable
from typing import Literal

from nicegui import ui

CHECK = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
)


def button(
    label: str,
    on_click: Callable[[], object],
    variant: Literal["primary", "secondary", "quiet"] = "secondary",
    keycap: str | None = None,
) -> ui.element:
    """Chunky arcade button: hard bottom shadow, pressed = shadow gone, 3 px down.

    `keycap` shows the hotkey next to the label, e.g. "Ctrl Alt P" (docs/ui.md).
    """
    with ui.element("button").classes(f"yt-btn yt-btn--{variant}").props('type="button"') as b:
        ui.label(label).classes("yt-btn-label")
        if keycap:
            ui.label(keycap).classes("yt-keycap")
    b.on("click", on_click)
    return b


def set_button_label(b: ui.element, label: str) -> None:
    next(child for child in b.default_slot.children if "yt-btn-label" in child.classes).set_text(
        label
    )


def saved_chip() -> None:
    with ui.element("span").classes("yt-chip yt-chip--ok"):
        ui.html(CHECK, sanitize=False)
        ui.label("Saved")


def switch(
    label: str, value: bool, on_change: Callable[[bool], object], disabled: bool = False
) -> ui.element:
    """On/off switch; the whole row is the click target."""
    state = {"on": value}
    with (
        ui.element("button")
        .classes("yt-switch-row")
        .props(f'type="button" role="switch" aria-checked="{str(value).lower()}"') as row
    ):
        ui.label(label).classes("yt-switch-label")
        ui.element("span").classes("yt-switch" + (" is-on" if value else ""))
    if disabled:
        row.props("disabled")

    def flip() -> None:
        state["on"] = not state["on"]
        row.props(f'aria-checked="{str(state["on"]).lower()}"')
        track = row.default_slot.children[1]
        if state["on"]:
            track.classes(add="is-on")
        else:
            track.classes(remove="is-on")
        on_change(state["on"])

    row.on("click", flip)
    return row
