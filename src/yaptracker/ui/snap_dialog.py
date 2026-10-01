"""The yap snap preview (#64, #65): exactly the PNG that gets saved, with its look next to it.

The look (preset, colours, font, switches) is remembered for the next snap. Hide names is not:
it starts on every time, so a snap is safe to post unless you decide otherwise.
"""

import re
from dataclasses import replace

from nicegui import ui

from yaptracker import config, logs, paths
from yaptracker.snaps import PRESETS, Style, preset_of, render, save, snap_lines, with_preset
from yaptracker.ui.components import button, switch

_FONTS = {"nunito": "Nunito Sans", "barlow": "Barlow Condensed"}
_COLOURS = {"background": "Background", "card": "Card", "text": "Text", "accent": "Accent",
            "team": "Team", "match": "Match"}  # fmt: skip
_SWITCHES = {"timestamps": "Times", "channel_labels": "Channel labels", "footer": "Match and date",
             "wordmark": "Wordmark", "rounded": "Round corners"}  # fmt: skip
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Copy (#155): the preview's own PNG to the clipboard, in the browser (WebView2 or --dev).
_COPY = (
    "(e) => { const img = document.querySelector('.yt-snap-preview img');"
    " if (!img || !navigator.clipboard || !window.ClipboardItem) { emit('no'); return; }"
    " fetch(img.src).then(r => r.blob())"
    ".then(b => navigator.clipboard.write([new ClipboardItem({'image/png': b})]))"
    ".then(() => emit('ok'), () => emit('no')); }"
)


def snap_dialog(messages: list, footer: str, started_at: float | None = 0.0) -> None:
    state = {"hide": True, "crew": False, "image": None,
             "style": Style.from_dict(config.snap_style())}  # fmt: skip
    with ui.dialog() as dialog, ui.element("section").classes("yt-card yt-snap"):
        with ui.element("div").classes("yt-card-body"):
            ui.label("Your yap snap").classes("yt-h2")
            preview = ui.image().classes("yt-snap-preview").mark("snap-preview")
            with ui.element("div").classes("yt-row yt-wrap"):
                switch("Hide names", True, lambda on: flip("hide", on)).mark("snap-hide")
                switch("Keep me & my crew", False, lambda on: flip("crew", on)).mark("snap-crew")
            ui.label(
                "Hidden names become Player 1, 2, 3... in the lines and in the text, so the snap "
                "is safe to post anywhere."
            ).classes("yt-hint")
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
            with ui.element("div").classes("yt-row yt-wrap"):
                for key, label in _SWITCHES.items():
                    switch(label, getattr(style, key), lambda on, k=key: toggle(k, on)).mark(
                        f"snap-{key}"
                    )

    def show_presets() -> None:
        style, box = state["style"], state["presets"]
        presets = {key: label for key, (label, _) in PRESETS.items()}
        if preset_of(style) is None:
            presets["custom"] = "Custom"
        box.clear()
        with box:
            segment(presets, preset_of(style) or "custom", pick_preset, "preset")

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
            state["style"] = with_preset(state["style"], key)
            restyle()

    def colour(key: str, value: str | None) -> None:
        if value and _HEX.match(value) and value != getattr(state["style"], key):
            restyle(redraw_controls=False, **{key: value.lower()})
            show_presets()  # now "Custom"; the colour pickers stay open

    def flip(key: str, on: bool) -> None:
        state[key] = on
        draw()

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
