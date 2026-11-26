"""Settings -> Translate chat -> who translates (#568): DeepL (the default) or an AI model via
OpenRouter with the user's own key, its model and a monthly limit in US dollars. Built inside the
Translate chat card."""

from collections.abc import Callable

from nicegui import run, ui

from yaptracker import config, paths, runtime
from yaptracker.ai_models import CACHE, Models

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


def may_check() -> bool:
    """OpenRouter's model list only with AI on, a key, and never during a match (#584)."""
    playing = runtime.matches is not None and runtime.matches.running
    return (config.translate_engine() == "ai" and bool(config.openrouter_key().strip())
            and not playing)  # fmt: skip


def ai_settings(saved: Callable[[], None]) -> None:
    """The engine choice and, with AI, its key, model and limit."""
    with ui.element("div").classes("yt-row yt-filters"):
        ui.label("Translated by").classes("yt-setting-name")
        engines = ui.element("div").classes("yt-seg").mark("translate-engine")
    block = ui.element("div").mark("ai-settings")
    with block:
        key = _field("OpenRouter key", "Your OpenRouter key (sk-or-...)", config.openrouter_key(),
                     "openrouter-key", password=True)  # fmt: skip
        with ui.element("div").classes("yt-row yt-filters"):
            ui.label("Model").classes("yt-setting-name")
            model = (
                ui.select([], value=None, with_input=True, new_value_mode="add-unique")
                .props("dense borderless")
                .classes("yt-search yt-grow")
                .mark("ai-model")
            )
        about = ui.label().classes("yt-hint").mark("ai-model-hint")
        ui.label(
            "Only models a provider that keeps nothing offers are listed (I check OpenRouter's "
            "list once a day while AI is on, never during a match). Type another model's name "
            "if you like: I'll say if it can't be used."
        ).classes("yt-hint")
        cap = _field("Monthly limit ($)", "1.00", f"{config.ai_cap():.2f}", "ai-cap")
        spend = ui.label().classes("yt-hint").mark("ai-spend")
        ui.label(AI_HINT).classes("yt-hint")

    models = Models(paths.data_dir() / CACHE)

    def show_models() -> None:
        hints, chosen = models.hints(), config.ai_model()
        model.set_options(list(dict.fromkeys([*hints, chosen])), value=chosen)
        problem = models.problem(chosen)
        about.set_text(problem or hints.get(chosen, ""))
        about.classes(**{"add" if problem else "remove": "yt-hint--warn"})

    def pick_model() -> None:
        chosen = str(model.value or "").strip()
        if chosen and chosen != config.ai_model():
            config.save_ai_model(chosen)  # never overwritten by the list: the user's choice
            saved()
        show_models()

    async def check_models() -> None:
        """OpenRouter's list, a day old at most (#584)."""
        if await run.io_bound(models.refresh, may_check()) and not model.is_deleted:
            show_models()

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

    def save_key() -> None:
        save(key, config.openrouter_key(), config.save_openrouter_key)
        ui.timer(0.1, check_models, once=True)  # a new key: the list may be due now

    key.on("blur", save_key)
    key.on("keydown.enter", save_key)
    model.on_value_change(pick_model)
    cap.on("blur", save_cap)
    cap.on("keydown.enter", save_cap)

    def choose(engine: str) -> None:
        config.save_translate_engine(engine)
        saved()
        show_engines()
        ui.timer(0.1, check_models, once=True)

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
    show_models()
    ui.timer(0.1, check_models, once=True)  # after the page is up


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
