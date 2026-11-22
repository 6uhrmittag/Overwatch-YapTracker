"""Settings -> Translate chat (#468): off by default, the user's own DeepL API Free key (or an
AI model via OpenRouter with theirs, #568), English or German. Lines that aren't clearly in a
language you read translate themselves (#469, #567), and the card says how much of the month's
free characters is used. Only a line's text goes to DeepL or the AI."""

from nicegui import run, ui

from yaptracker import config, runtime
from yaptracker.languages import NAMES
from yaptracker.translate import TARGETS
from yaptracker.ui.ai_settings import ai_settings
from yaptracker.ui.components import saved_chip, switch

PRIVACY = (
    "Only the text of a line goes to DeepL or the AI, with your own key: one you translate, or "
    "(with Translate automatically) every line from others that isn't clearly in a language "
    "you read, plus the text of a few lines before it so the meaning comes across. Never "
    "names, pictures or ids."
)
NO_USAGE = "DeepL: the characters you used this month show here once your key works."
PAUSED = (
    " Translate automatically is paused until DeepL's month starts over: what's left is for "
    "the lines you click."
)


def usage_words(usage) -> str:
    """ "DeepL: 41,250 of 500,000 characters used this month." (#567)"""
    if usage is None:
        return NO_USAGE
    said = f"DeepL: {usage.used:,} of {usage.limit:,} characters used this month."
    return said + (PAUSED if usage.near else "")


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
            ai_settings(lambda: saved())  # DeepL or AI (#568)
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
                hint="Every line from others that isn't clearly in a language you read goes to "
                "DeepL or the AI and gets its translation within a second or two, no click "
                "needed. "
                "Yours and your crew's, gg and the like stay here.",
            ).mark("translate-auto-switch")
            deepl = getattr(runtime.translator, "deepl", runtime.translator)  # also with AI
            known = deepl.usage(ask=False) if deepl else None
            used = ui.label(usage_words(known)).classes("yt-hint").mark("deepl-usage")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("I read").classes("yt-setting-name")
                read = ui.element("div").classes("yt-seg yt-seg--wrap").mark("read-languages")
            ui.label(SCRIPTS).classes("yt-hint")
            ui.label(PRIVACY).classes("yt-hint")

    def saved() -> None:
        status.clear()
        with status:
            saved_chip()

    async def show_usage() -> None:
        """DeepL's own count, asked off the UI thread (at most every 10 minutes)."""
        translator = getattr(runtime.translator, "deepl", runtime.translator)  # also with AI
        if translator is None or not config.translate_chat():  # switched off: DeepL isn't asked
            return
        try:
            usage = await run.io_bound(translator.usage)
        except Exception:  # the hint stays
            return
        if not used.is_deleted:
            used.set_text(usage_words(usage))

    def save_key() -> None:
        value = (key.value or "").strip()
        if value != config.deepl_key():
            config.save_deepl_key(value)
            saved()
            ui.timer(0.1, show_usage, once=True)  # the new key's count

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
    ui.timer(0.1, show_usage, once=True)
