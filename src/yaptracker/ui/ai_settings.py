"""Settings -> Translate chat -> who translates (#568): DeepL (the default) or an AI model via
OpenRouter with the user's own key, its model and a monthly limit in US dollars. Built inside the
Translate chat card."""

from collections.abc import Callable

from nicegui import ui

from yaptracker import config, runtime
from yaptracker.ai_translate import DEFAULT_MODEL

ENGINES = {"deepl": "DeepL", "ai": "AI (OpenRouter)"}
AI_HINT = (
    "An AI model reads gamer slang, typos and in-game jargon far better than DeepL. Your own "
    "key from openrouter.ai (pay as you go: a line costs about a hundredth of a cent). Only "
    "providers that keep nothing are asked. With a DeepL key too, DeepL steps in when the AI "
    "can't (offline, slow, the limit)."
)


def spend_words(used: float | None, cap: float) -> str:
    """ "AI: $0.04 of $1.00 used this month." """
    if used is None:
        return "AI: what this month's translations cost shows here."
    said = f"AI: ${used:.2f} of ${cap:.2f} used this month."
    return said + (" The limit is reached: nothing goes to the AI until next month."
                   if used >= cap else "")  # fmt: skip


def _spent() -> float | None:
    ai = getattr(runtime.translator, "ai", None)
    return ai.spend.used() if ai is not None else None


def ai_settings(saved: Callable[[], None]) -> None:
    """The engine choice and, with AI, its key, model and limit."""
    with ui.element("div").classes("yt-row yt-filters"):
        ui.label("Translated by").classes("yt-setting-name")
        engines = ui.element("div").classes("yt-seg").mark("translate-engine")
    block = ui.element("div").mark("ai-settings")
    with block:
        key = _field("OpenRouter key", "Your OpenRouter key (sk-or-...)", config.openrouter_key(),
                     "openrouter-key", password=True)  # fmt: skip
        model = _field("Model", DEFAULT_MODEL, config.ai_model(), "ai-model")
        cap = _field("Monthly limit ($)", "1.00", f"{config.ai_cap():.2f}", "ai-cap")
        spend = ui.label().classes("yt-hint").mark("ai-spend")
        ui.label(AI_HINT).classes("yt-hint")

    def show_spend() -> None:
        spend.set_text(spend_words(_spent(), config.ai_cap()))

    def save(field, now: str, store: Callable[[str], None]) -> None:
        value = (field.value or "").strip()
        if value != now:
            store(value)
            saved()
            show_spend()

    def save_cap() -> None:
        try:
            usd = float((cap.value or "").replace(",", ".").replace("$", "").strip())
        except ValueError:
            cap.value = f"{config.ai_cap():.2f}"  # not a number: the saved one stays
            return
        if abs(usd - config.ai_cap()) > 1e-9:
            config.save_ai_cap(usd)
            saved()
        cap.value = f"{config.ai_cap():.2f}"
        show_spend()

    for field, now, store in ((key, config.openrouter_key, config.save_openrouter_key),
                              (model, config.ai_model, config.save_ai_model)):  # fmt: skip
        handler = lambda f=field, n=now, s=store: save(f, n(), s)  # noqa: E731
        field.on("blur", handler)
        field.on("keydown.enter", handler)
    cap.on("blur", save_cap)
    cap.on("keydown.enter", save_cap)

    def choose(engine: str) -> None:
        config.save_translate_engine(engine)
        saved()
        show_engines()

    def show_engines() -> None:
        engines.clear()
        chosen = config.translate_engine()
        with engines:
            for code, name in ENGINES.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"engine-{code}")
                if code == chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                with item:
                    ui.label(name)
                item.on("click", lambda code=code: choose(code))
        block.classes(**{"remove" if chosen == "ai" else "add": "yt-hidden"})

    show_engines()
    show_spend()


def _field(name: str, placeholder: str, value: str, mark: str, password: bool = False):
    with ui.element("div").classes("yt-row yt-filters"):
        ui.label(name).classes("yt-setting-name")
        return (
            ui.input(
                placeholder=placeholder,
                value=value,
                password=password,
                password_toggle_button=password,
            )  # fmt: skip
            .props("dense borderless")
            .classes("yt-search yt-grow")
            .mark(mark)
        )
