"""Settings -> Me & my crew (#74): my own names and my regular group. Saves on every change.

Both are lists (#162): Enter, the Add button or just clicking elsewhere adds the typed name, so
nothing typed is ever lost, and the field says "Add another" once there is one.
"""

from nicegui import ui

from yaptracker import config
from yaptracker.identity import clean
from yaptracker.ui.components import saved_chip

# Read the field in the browser and empty it; on blur only if something was typed.
_TAKE = "(e) => { emit(e.target.value); e.target.value = ''; }"
_TAKE_TYPED = "(e) => { if (e.target.value.trim()) { emit(e.target.value); e.target.value = ''; } }"
_TAKE_FIELD = (
    "(e) => { const f = e.currentTarget.parentElement.querySelector('input'); "
    "emit(f.value); f.value = ''; }"
)
_FIELDS = (
    ("me", "My names", "Your BattleTag, e.g. Marv#2718", "Another name you play as\u2026", None),
    ("crew", "My crew", "e.g. Void", "Add another\u2026",
     "Add everyone you usually queue with, as many as you like."),
)  # fmt: skip

_REMOVE = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="3" stroke-linecap="round" aria-hidden="true">'
    '<path d="M6 6l12 12M18 6L6 18"/></svg>'
)


def _remove_button(name: str, on_click) -> None:
    button = ui.element("button").classes("yt-chip-remove")
    button.props(f'type="button" aria-label="Remove {name}" title="Remove"').on("click", on_click)
    button.mark(f"remove-{name}")
    with button:
        ui.html(_REMOVE, sanitize=False)


def crew_card() -> None:
    identity = config.identity()
    names = {"me": list(identity.me), "crew": list(identity.crew)}

    with ui.element("section").classes("yt-card").mark("crew"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Me & my crew").classes("yt-h2")
            status = ui.element("div")
        with ui.element("div").classes("yt-card-body"):
            ui.label(
                "Your own lines show as you. Your crew is logged like everyone else, "
                "but never gets a “Look who's back!”."
            ).classes("yt-hint")
            lists = ui.element("div").classes("yt-crew-lists")

    chips: dict[str, ui.element] = {}
    fields: dict[str, ui.element] = {}

    def save() -> None:
        config.save_identity(names["me"], names["crew"])
        status.clear()
        with status:
            saved_chip()
        show_names()

    def add(key: str, value: str) -> None:
        name = value.strip()
        known = {clean(n).lower() for n in names["me"] + names["crew"]}
        if name and clean(name).lower() not in known:
            names[key].append(name)
            save()

    def remove(key: str, name: str) -> None:
        names[key].remove(name)
        save()

    def show_names() -> None:
        """Only the chips change: the field stays as it is, focused, ready for the next name."""
        for key, _, first, more, _ in _FIELDS:
            chips[key].clear()
            with chips[key]:
                for name in names[key]:
                    with ui.element("span").classes("yt-name-chip"):
                        ui.label(name)
                        _remove_button(name, lambda key=key, name=name: remove(key, name))
            fields[key].props(f'placeholder="{more if names[key] else first}"')

    with lists:
        for key, label, _, _, hint in _FIELDS:
            with ui.element("div").classes("yt-crew-list"):
                ui.label(label).classes("yt-label")
                chips[key] = ui.element("div").classes("yt-name-chips")
                with ui.element("div").classes("yt-row yt-crew-add"):
                    field = ui.element("input").classes("yt-input yt-grow")
                    field.props(f'type="text" aria-label="{label}"').mark(f"add-{key}")
                    fields[key] = field

                    def take(e, key=key) -> None:
                        add(key, e.args)

                    field.on("keydown.enter", take, js_handler=_TAKE)
                    field.on("blur", take, js_handler=_TAKE_TYPED)  # typed, then clicked away
                    plus = ui.element("button").classes("yt-btn yt-btn--secondary")
                    plus.props('type="button"').mark(f"add-{key}-button")
                    with plus:
                        ui.label("Add").classes("yt-btn-label")
                    plus.on("click", take, js_handler=_TAKE_FIELD)
                if hint:
                    ui.label(hint).classes("yt-hint")
    show_names()
