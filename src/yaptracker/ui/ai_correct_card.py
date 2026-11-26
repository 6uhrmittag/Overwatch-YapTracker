"""Settings -> AI correction (#637): doubtful chat lines re-read from their picture by an AI.
On by default once an OpenRouter key is set (the same key as AI translation, #568). Every
state in words: what it costs, how many lines tonight, why it's not working."""

import time
from datetime import datetime, timedelta

from nicegui import ui

from yaptracker import ai_correct, config, runtime
from yaptracker.days import CUT_H, day_of
from yaptracker.ui.ai_settings import _field
from yaptracker.ui.components import switch

HINT = (
    "Lines I'm unsure of go to an AI as the picture of that one line, names included; hover "
    '"AI-corrected" for what OCR read. Your edits always win. About a cent an evening.'
)


def evening_start(now: float) -> float:
    """05:00 of the evening `now` belongs to (days.py): when "tonight" began."""
    day = datetime.fromisoformat(day_of(now))
    return (day + timedelta(hours=CUT_H)).timestamp()


def status_words(key: bool, on: bool, corrected: int, sent: int, used: float | None,
                 cap: float) -> str:  # fmt: skip
    if not on:
        return "Off: lines stay as OCR read them."
    if not key:
        return "Needs an OpenRouter key (above): nothing is sent."
    said = (f"Tonight: {corrected} line{'s' if corrected != 1 else ''} corrected, {sent} looked "
            f"at (at most {ai_correct.EVENING_LIMIT} a night).")  # fmt: skip
    if used is not None:
        said += f" The AI this month: ${used:.2f} of ${cap:.2f}."
        if used >= cap:
            said += " The limit is reached: nothing goes to the AI until next month."
    return said


def ai_correct_card() -> None:
    with ui.element("section").classes("yt-card").mark("ai-correct"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("AI correction").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            switch(
                "Correct doubtful lines with AI",
                config.ai_correct(),
                lambda on: (config.save_ai_correct(on), show()),
                hint=HINT,
            ).mark("ai-correct-switch")
            key = _field("OpenRouter key", "Your OpenRouter key (sk-or-...)",
                         config.openrouter_key(), "ai-correct-key", password=True)  # fmt: skip
            ui.label(
                "The same key and monthly limit as AI translation. Only providers that keep "
                "nothing are asked."
            ).classes("yt-hint")
            status = ui.label().classes("yt-hint").mark("ai-correct-status")

    def save_key() -> None:
        if (key.value or "").strip() != config.openrouter_key():
            config.save_openrouter_key(key.value or "")
        show()

    def show() -> None:
        worker = runtime.ai_corrector
        store, now = runtime.store, time.time()
        corrected = store.corrected_since(evening_start(now)) if store is not None else 0
        sent = worker.sent_tonight if worker is not None else 0
        spend = runtime.ai_spend
        status.set_text(status_words(
            bool(config.openrouter_key().strip()), config.ai_correct(), corrected, sent,
            spend.used() if spend is not None else None, config.ai_cap()))  # fmt: skip

    key.on("blur", save_key)
    key.on("keydown.enter", save_key)
    show()
    ui.timer(10.0, show)  # tonight's count moves while you play
