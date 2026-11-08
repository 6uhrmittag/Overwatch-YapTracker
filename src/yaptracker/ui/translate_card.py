"""Settings -> Translate chat (#468): off by default, the user's own DeepL API Free key, English
or German. Lines in a language you don't read translate themselves (#469). Only a line's text
goes to DeepL."""

from nicegui import ui

from yaptracker import config
from yaptracker.languages import NAMES
from yaptracker.translate import TARGETS
from yaptracker.ui.components import saved_chip, switch

PRIVACY = (
    "Only the text of a line goes to DeepL, with your own key: one you translate, or one in a "
    "language you don't read. Never names, pictures or ids."
)
SCRIPTS = (
    "Reads Latin-script languages (Spanish, French, Polish, ...). Cyrillic, Greek and Asian "
    "scripts aren't read from the screen at all yet."
)


def translate_card() -> None:
    with ui.element("section").classes("yt-card").mark("translate"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Translate chat").classes("yt-h2")
            status = ui.element("div")
        with ui.element("div").classes("yt-card-body"):
            switch(
                "Translate chat",
                config.translate_chat(),
                config.save_translate_chat,
                hint="Adds Translate to every chat line in Live, matches and profiles.",
            ).mark("translate-switch")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("DeepL key").classes("yt-setting-name")
                key = (
                    ui.input(
                        placeholder="Your DeepL API Free key (ends in :fx)",
                        value=config.deepl_key(),
                        password=True,
                        password_toggle_button=True,
                    )  # fmt: skip
                    .props("dense borderless")
                    .classes("yt-search yt-grow")
                    .mark("deepl-key")
                )
            ui.label(
                "Free at deepl.com/pro-api: sign up for DeepL API Free (500,000 characters a "
                "month, far more than a chat needs) and copy the key from your account."
            ).classes("yt-hint")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Translate to").classes("yt-setting-name")
                targets = ui.element("div").classes("yt-seg").mark("translate-to")
            switch(
                "Translate automatically",
                config.translate_auto(),
                config.save_translate_auto,
                hint="Lines in a language you don't read get their translation within a second "
                "or two, no click needed. Yours and your crew's are left alone.",
            ).mark("translate-auto-switch")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("I read").classes("yt-setting-name")
                read = ui.element("div").classes("yt-seg yt-seg--wrap").mark("read-languages")
            ui.label(SCRIPTS).classes("yt-hint")
            ui.label(PRIVACY).classes("yt-hint")

    def saved() -> None:
        status.clear()
        with status:
            saved_chip()

    def save_key() -> None:
        value = (key.value or "").strip()
        if value != config.deepl_key():
            config.save_deepl_key(value)
            saved()

    key.on("blur", save_key)
    key.on("keydown.enter", save_key)

    def choose(target: str) -> None:
        config.save_translate_to(target)
        saved()
        show_targets()
        show_read()  # the language translated into always counts as read

    def flip_read(code: str) -> None:
        if code == config.translate_to():
            return  # translated into: always read
        config.save_read_languages(config.read_languages() ^ {code})  # the target stays in
        saved()
        show_read()

    def show_read() -> None:
        read.clear()
        chosen, target = config.read_languages(), config.translate_to()
        with read:
            for code, name in NAMES.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"read-{code}")
                if code in chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                if code == target:  # translated into: read, whatever you pick
                    item.props(f'title="You translate into {name}, so you read it"')
                with item:
                    ui.label(name)
                item.on("click", lambda code=code: flip_read(code))

    def show_targets() -> None:
        targets.clear()
        chosen = config.translate_to()
        with targets:
            for code, name in TARGETS.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"translate-to-{code}")
                if code == chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(name)
                item.on("click", lambda code=code: choose(code))

    show_targets()
    show_read()
