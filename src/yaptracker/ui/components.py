"""Shared building blocks from the style kit (docs/ui/mockup/Kit.dc.html)."""

import time
from collections.abc import Callable, Sequence
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


def stepper(steps: Sequence[str], current: int) -> None:
    """Setup steps (docs/ui/mockup/Setup): done ones get a check, the current one is orange."""
    with ui.element("ol").classes("yt-steps").props('aria-label="Setup steps"'):
        for n, label in enumerate(steps, start=1):
            if n > 1:
                ui.element("li").classes("yt-step-line").props('aria-hidden="true"')
            state = "done" if n < current else "current" if n == current else "next"
            with ui.element("li").classes(f"yt-step yt-step--{state}") as item:
                with ui.element("span").classes("yt-step-dot"):
                    if state == "done":
                        ui.html(CHECK.replace('"16"', '"14"'), sanitize=False)
                    else:
                        ui.label(str(n))
                ui.label(label)
            if state == "current":
                item.props('aria-current="step"')


# Verdict stickers (docs/ui.md): stored value -> label and icon (Kit mockup). Colours in CSS.
_HEART = (
    '<path d="M12 21s-7.5-4.6-9.5-9.3C1 8.1 3.3 4.5 7 4.5c2 0 3.6 1.1 5 3 1.4-1.9 3-3 5-3 '
    '3.7 0 6 3.6 4.5 7.2C19.5 16.4 12 21 12 21z" fill="currentColor" stroke="none"/>'
)
_STAR = (
    '<path d="M12 2l2.6 6.3L21 9l-5 4.3L17.6 20 12 16.6 6.4 20 8 13.3 3 9l6.4-.7z" '
    'fill="currentColor" stroke="none"/>'
)
_FLAT = '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 15h7M9 9.5h.01M15 9.5h.01"/>'
_NO_ENTRY = '<circle cx="12" cy="12" r="8.5"/><path d="M6 18L18 6"/>'
VERDICTS = {
    "friend": ("Bestie", _HEART),
    "fun": ("Fun", _STAR),
    "neutral": ("Meh", _FLAT),
    "avoid": ("Nope", _NO_ENTRY),
}


def sticker(verdict: str) -> ui.element:
    """A tilted verdict sticker: Bestie / Fun / Meh / Nope."""
    label, icon = VERDICTS[verdict]
    with ui.element("span").classes(f"yt-sticker yt-sticker--{verdict}") as element:
        ui.html(
            f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2.6" stroke-linecap="round" aria-hidden="true">{icon}</svg>',
            sanitize=False,
        )
        ui.label(label)
    return element


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


def when(ts: float | None, now: float | None = None) -> str:
    """'today', 'yesterday', 'Tuesday' within a week, else 'Sep 28'."""
    if ts is None:
        return "never"
    now = time.time() if now is None else now
    day, today = time.localtime(ts), time.localtime(now)
    days = (time.mktime(today[:3] + (0, 0, 0, 0, 0, -1)) -
            time.mktime(day[:3] + (0, 0, 0, 0, 0, -1))) // 86400  # fmt: skip
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return time.strftime("%A", day)
    return time.strftime("%b %d", day).replace(" 0", " ")
