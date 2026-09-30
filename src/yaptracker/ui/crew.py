"""Settings -> Me & my crew (#74): my own names and my regular group. Saves on every change."""

from nicegui import ui

from yaptracker import config
from yaptracker.identity import clean
from yaptracker.ui.components import saved_chip

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

    def save() -> None:
        config.save_identity(names["me"], names["crew"])
        status.clear()
        with status:
            saved_chip()
        render()

    def add(key: str, value: str) -> None:
        name = value.strip()
        known = {clean(n).lower() for n in names["me"] + names["crew"]}
        if name and clean(name).lower() not in known:
            names[key].append(name)
            save()

    def remove(key: str, name: str) -> None:
        names[key].remove(name)
        save()

    def render() -> None:
        lists.clear()
        with lists:
            for key, label, placeholder in (
                ("me", "My names", "Your BattleTag, e.g. Marv#2718"),
                ("crew", "My crew", "e.g. Void"),
            ):
                with ui.element("div").classes("yt-crew-list"):
                    ui.label(label).classes("yt-label")
                    with ui.element("div").classes("yt-name-chips"):
                        for name in names[key]:
                            with ui.element("span").classes("yt-name-chip"):
                                ui.label(name)
                                _remove_button(name, lambda key=key, name=name: remove(key, name))
                    ui.element("input").classes("yt-input").props(
                        f'type="text" placeholder="{placeholder}" aria-label="{label}"'
                    ).mark(f"add-{key}").on(
                        "keydown.enter",
                        lambda e, key=key: add(key, e.args),
                        js_handler="(e) => { emit(e.target.value); e.target.value = ''; }",
                    )

    render()
