"""The yap snap preview (#64, #65): exactly the PNG that gets saved, with its look next to it.

The look (preset, colours, font, switches) is remembered for the next snap. Hide names is not:
it starts off every time (Marv, #366: snaps mostly go to friends, and switching names back on
for each snap was the annoying part). Switch it on for a snap you post anywhere.
"""

import re
from dataclasses import replace

from nicegui import ui

from yaptracker import chat_colours, config, logs, paths
from yaptracker.snaps import PRESETS, preset_of, remembered, render, save, snap_lines, with_preset
from yaptracker.ui.components import allow_switch, button, switch

_FONTS = {"nunito": "Nunito Sans", "barlow": "Barlow Condensed"}
_COLOURS = {"background": "Background", "card": "Card", "text": "Text", "accent": "Accent",
            "team": "Team", "match": "Match"}  # fmt: skip
_CREW_WHY = "Only with Hide names: right now every name is shown."
_SWITCHES = {  # (label, its hint)
    "timestamps": ("Times", "The time each line was written, in front of it."),
    "channel_labels": ("Channel labels", "TEAM, MATCH or GROUP in front of every line."),
    "footer": ("Match and date", "The match and the day along the bottom."),
    "wordmark": ("Wordmark", "YapTracker in the bottom corner."),
    "rounded": ("Round corners", "Soft corners on the picture."),
}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Copy (#155): the preview's own PNG to the clipboard, in the browser (WebView2 or --dev).
_COPY = (
    "(e) => { const img = document.querySelector('.yt-snap-preview img');"
    " if (!img || !navigator.clipboard || !window.ClipboardItem) { emit('no'); return; }"
    " fetch(img.src).then(r => r.blob())"
    ".then(b => navigator.clipboard.write([new ClipboardItem({'image/png': b})]))"
    ".then(() => emit('ok'), () => emit('no')); }"
)


def snap_dialog(messages: list, footer: str, started_at: float | None = 0.0) -> None:  # noqa: C901 - split up after v1 (#311)
    state = {"hide": False, "crew": False, "image": None,
             "style": remembered(config.snap_style(), chat_colours.current())}  # fmt: skip
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-snap"):
        with ui.element("div").classes("yt-card-body"):
            ui.label("Your yap snap").classes("yt-h2")
            preview = ui.image().classes("yt-snap-preview").mark("snap-preview")
            with ui.element("div").classes("yt-switches"):  # one per row, each its hint (#397)
                switch(
                    "Hide names",
                    False,
                    lambda on: hide(on),
                    hint="Before you share: hidden names become Player 1, 2, 3... in the lines "
                    "and in the text.",
                ).mark("snap-hide")
                crew = switch(
                    "Keep me & my crew",
                    False,
                    lambda on: flip("crew", on),
                    hint="With Hide names: your own name and your crew's stay readable.",
                ).mark("snap-crew")
                allow_switch(crew, False, _CREW_WHY)
            looks = ui.element("div").classes("yt-snap-looks").mark("snap-looks")
            with ui.element("div").classes("yt-row"):
                button("Save PNG", lambda: keep(), "primary").mark("snap-save")
                copy = ui.element("button").classes("yt-btn yt-btn--secondary")
                copy.props('type="button"').mark("snap-copy")
                with copy:
                    ui.label("Copy").classes("yt-btn-label")
                copy.on("click", lambda e: copied(e.args), js_handler=_COPY)
                saved = ui.label().classes("yt-hint yt-mono").mark("snap-saved")
                ui.element("div").classes("yt-grow")
                button("Close", dialog.close, "quiet")

    def segment(options: dict, chosen, choose, key: str) -> None:
        with ui.element("div").classes("yt-seg").mark(f"snap-{key}s"):
            for value, label in options.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"snap-{key}-{value}")
                if value == chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(label)
                item.on("click", lambda value=value: choose(value))

    def controls() -> None:
        style = state["style"]
        looks.clear()
        with looks:
            state["presets"] = ui.element("div")
            show_presets()
            segment(_FONTS, style.font, lambda f: restyle(font=f), "font")
            with ui.element("div").classes("yt-row yt-wrap"):
                for key, label in _COLOURS.items():
                    picker = ui.color_input(
                        label,
                        value=getattr(style, key),
                        on_change=lambda e, k=key: colour(k, e.value),
                    )
                    picker.props("dense").classes("yt-snap-colour").mark(f"snap-colour-{key}")
            with ui.element("div").classes("yt-switches"):
                for key, (label, hint) in _SWITCHES.items():
                    switch(
                        label, getattr(style, key), lambda on, k=key: toggle(k, on), hint=hint
                    ).mark(f"snap-{key}")

    def show_presets() -> None:
        style, box = state["style"], state["presets"]
        presets = {key: label for key, (label, _) in PRESETS.items()}
        chosen = preset_of(style, chat_colours.current())
        if chosen is None:
            presets["custom"] = "Custom"
        box.clear()
        with box:
            segment(presets, chosen or "custom", pick_preset, "preset")

    def draw() -> None:
        lines = snap_lines(messages, state["hide"], state["crew"], started_at)
        state["image"] = render(lines, footer, state["style"])
        preview.set_source(state["image"])
        saved.set_text("")

    def restyle(redraw_controls: bool = True, **changes) -> None:
        state["style"] = replace(state["style"], **changes)
        config.save_snap_style(state["style"].to_dict())
        if redraw_controls:
            controls()
        draw()

    def toggle(key: str, on: bool) -> None:
        restyle(redraw_controls=False, **{key: on})

    def pick_preset(key: str) -> None:
        if key in PRESETS:
            state["style"] = with_preset(state["style"], key, chat_colours.current())
            restyle()

    def colour(key: str, value: str | None) -> None:
        if value and _HEX.match(value) and value != getattr(state["style"], key):
            restyle(redraw_controls=False, **{key: value.lower()})
            show_presets()  # now "Custom"; the colour pickers stay open

    def flip(key: str, on: bool) -> None:
        state[key] = on
        draw()

    def hide(on: bool) -> None:
        state["crew"] = state["crew"] and on
        allow_switch(crew, on, _CREW_WHY)
        flip("hide", on)

    def copied(result) -> None:
        saved.set_text("Copied: paste it into Discord or WhatsApp." if result == "ok"
                       else "Couldn't copy here, but Save PNG works.")  # fmt: skip

    def keep() -> None:
        path = save(state["image"], paths.pictures_dir())
        saved.set_text(f"Saved to {path}")
        if logs.folder_opens():
            logs.open_folder(path.parent)

    dialog.on_value_change(lambda e: None if e.value else dialog.delete())  # gone once closed
    controls()
    draw()
    dialog.open()
