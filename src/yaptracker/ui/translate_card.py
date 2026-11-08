"""Settings -> Translate chat (#468): off by default, the user's own DeepL API Free key, English
or German. Only the text of a line you translate goes to DeepL."""

from nicegui import ui

from yaptracker import config
from yaptracker.translate import TARGETS
from yaptracker.ui.components import saved_chip, switch

PRIVACY = (
    "Only the text of a line you translate goes to DeepL, with your own key. Never names, "
    "pictures or ids."
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
