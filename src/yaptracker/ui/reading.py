"""Settings -> Reading (#152): how the chat is read during Competitive and other matches (#331),
and how often. Applies at once."""

import time
from datetime import datetime, timedelta

from nicegui import ui

from yaptracker import ai_correct, config, runtime
from yaptracker import reading_mode as modes
from yaptracker.days import CUT_H, day_of
from yaptracker.ocr import engine as ocr
from yaptracker.ui.components import switch

# Windows OCR isn't an everyday choice (#640): it reads "Live, light" and steps in when nothing
# else starts; the calibration preview still offers it, to compare on the same picture.
_ENGINES = {name: ocr.LABELS[name] for name in (ocr.DEFAULT, ocr.ChatTrainedOcrEngine.name)}
_GAPS = {1.5: "Every 1.5 s", 3.0: "Every 3 s", 0.0: "As fast as it can (strong PCs)"}
_MODES = {
    modes.AFTER: "After the match",
    modes.LIGHT: "Live, light",
    modes.BEST: "Live, best quality",
}


def reading_card() -> None:
    with ui.element("section").classes("yt-card").mark("reading"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Reading").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Reading engine").classes("yt-setting-name")
                reader = ui.element("div").classes("yt-seg").mark("reading-engine")
            ui.label(
                "What reads your chat with the best quality, and tidies up after light reading. "
                "Classic is the tried one, Chat-trained learned from Overwatch chat itself."
            ).classes("yt-hint").mark("reading-engine-hint")
            fallback = ui.label().classes("yt-hint yt-hidden").mark("reading-engine-fallback")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Competitive").classes("yt-setting-name")
                competitive = ui.element("div").classes("yt-seg").mark("reading-competitive")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Other matches").classes("yt-setting-name")
                other = ui.element("div").classes("yt-seg").mark("reading-other")
            ui.label(
                "Light reads live with Windows OCR and costs your game almost nothing; "
                "afterwards I tidy up with your reading engine. Best reads live with your "
                "reading engine, for the most accurate lines right away."
            ).classes("yt-hint").mark("reading-other-hint")
            ui.label(
                "After the match costs your game nothing: I keep the chat pictures and read them "
                "once it's over, so faces show up after the match. Between matches I always read "
                "with the best quality: the game is idle then."
            ).classes("yt-hint")
            ui.label(
                "Competitive is spotted at hero select. If I can't tell (glare, or I started "
                "mid-match), I use the lighter of the two."
            ).classes("yt-hint")
            problem = ui.label().classes("yt-hint yt-hidden").mark("reading-light-problem")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Read the chat").classes("yt-setting-name")
                gaps = ui.element("div").classes("yt-seg").mark("reading-gaps")
            ui.label(
                "Every 3 s is lighter on the CPU, but a fast burst of chat can push a line out "
                "of the box before I read it. As fast as it can catches the most lines, but "
                "costs about a whole CPU core while chat is busy: only for strong PCs."
            ).classes("yt-hint")
            ui.label(
                "When I use more CPU than planned, I read every 3 s for a minute, unless a match "
                "is read live with the best quality: that's your choice. When the game leaves "
                "me no core at all, I read every 3 s for a minute whatever you chose."
            ).classes("yt-hint")
            ai_correction_row()  # doubtful lines re-read by an AI (#637)

    def segment(container, options: dict, chosen, choose, key: str, disabled=()) -> None:
        container.clear()
        with container:
            for value, label in options.items():
                item = ui.element("button").classes("yt-seg-item").props('type="button"')
                item.mark(f"{key}-{value}")
                if value == chosen:
                    item.classes(add="is-active").props('aria-pressed="true"')
                if value in disabled:
                    item.props('disabled title="Windows only"')
                with item:
                    ui.label(label)
                item.on("click", lambda value=value: choose(value))

    def choose(kind: str, choice: str) -> None:
        config.save_reading(kind, choice)  # the next read already uses it
        render()

    def choose_gap(seconds: float) -> None:
        config.save_read_every_s(seconds)
        if runtime.reader is not None:
            runtime.reader.min_gap_s = seconds  # the next read already waits this long
        render()

    def choose_engine(name: str) -> None:
        config.save_ocr_engine(name)  # the next best-quality read uses it (#640)
        if runtime.reading is not None:
            runtime.reading.retry_best()  # chosen again: try it again
        ocr.warm_up(name)  # loaded in the background: the first read doesn't wait
        if runtime.ocr_child is not None:  # ...and in the reader's own process (#563)
            runtime.ocr_child.warm_up(name)
        render()

    def render() -> None:
        for kind, container in (("competitive", competitive), ("other", other)):
            chosen = config.reading(kind)
            segment(container, _MODES, chosen, lambda c, kind=kind: choose(kind, c), kind)
        why = runtime.reading.light_problem if runtime.reading is not None else None
        problem.set_text(f"Light reading can't run here ({why}): I read with the best quality.")
        problem.classes(**{"remove" if why else "add": "yt-hidden"})
        segment(gaps, _GAPS, config.read_every_s(), choose_gap, "gap")
        chosen = config.ocr_engine()
        segment(reader, _ENGINES, chosen, choose_engine, "engine")
        fallback.set_text(engine_words(chosen, runtime.reading))
        fallback.classes(**{"remove" if fallback.text else "add": "yt-hidden"})

    render()


def engine_words(chosen: str, reading) -> str:
    """The reading engine's state when it isn't simply the one chosen (#640); "" otherwise."""
    if chosen not in _ENGINES:
        return (f"{ocr.LABELS.get(chosen, chosen)} is chosen (in Calibrate's preview): it reads "
                "with the best quality.")  # fmt: skip
    problem = getattr(reading, "best_problem", None)
    if problem and problem[0] == chosen:
        return (f"{ocr.LABELS[chosen]} can't start here ({problem[1]}): I read with "
                f"{ocr.LABELS[ocr.DEFAULT]}. Choose it again to try once more.")  # fmt: skip
    return ""


def evening_start(now: float) -> float:
    """05:00 of the evening `now` belongs to (days.py): when "tonight" began."""
    day = datetime.fromisoformat(day_of(now))
    return (day + timedelta(hours=CUT_H)).timestamp()


def ai_words(key: bool, on: bool, corrected: int, sent: int, used: float | None,
             cap: float) -> str:  # fmt: skip
    """AI correction's state in words (#637). Without a key the link to it follows."""
    if not on:
        return "Off: lines stay as OCR read them."
    if not key:
        return "Needs an OpenRouter key: nothing is sent. Set it under"
    said = (f"Tonight: {corrected} line{'s' if corrected != 1 else ''} corrected, {sent} looked "
            f"at (at most {ai_correct.EVENING_LIMIT} a night).")  # fmt: skip
    if used is not None:
        said += f" The AI this month: ${used:.2f} of ${cap:.2f}."
        if used >= cap:
            said += " The limit is reached: nothing goes to the AI until next month."
    return said


def ai_correction_row() -> None:
    """Doubtful lines re-read by an AI from their picture (#637). The OpenRouter key stays in
    its one place, Translate chat -> AI (#640): without it this row says so and links there."""
    switch(
        "AI correction",
        config.ai_correct(),
        lambda on: (config.save_ai_correct(on), show()),
        hint=(
            "Lines I'm unsure of go to an AI as the picture of that one line, names included; "
            'hover "AI-corrected" for what OCR read. Your edits always win. About a cent an '
            "evening."
        ),
    ).mark("ai-correct-switch")
    with ui.element("p").classes("yt-hint").mark("ai-correct-status"):
        status = ui.label().style("display: inline")
        where = ui.link("Translate chat → AI", "#translate").style(
            "color: var(--yt-accent); margin-left: 4px"
        )
        where.mark("ai-correct-key-link")

    def show() -> None:
        worker, store, now = runtime.ai_corrector, runtime.store, time.time()
        corrected = store.corrected_since(evening_start(now)) if store is not None else 0
        sent = worker.sent_tonight if worker is not None else 0
        spend = runtime.ai_spend
        key, on = bool(config.openrouter_key().strip()), config.ai_correct()
        status.set_text(
            ai_words(
                key,
                on,
                corrected,
                sent,
                spend.used() if spend is not None else None,
                config.ai_cap(),
            )
        )
        where.classes(**{"remove" if on and not key else "add": "yt-hidden"})  # fmt: skip

    show()
    ui.timer(10.0, show)  # tonight's count moves while you play
