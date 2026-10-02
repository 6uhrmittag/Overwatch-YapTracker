"""Settings -> Reading (#152): which OCR engine reads the chat, and how often. Applies at once."""

from nicegui import ui

from yaptracker import config, runtime
from yaptracker.ocr import engine as ocr
from yaptracker.ui.components import switch

_GAPS = {1.5: "Every 1.5 s", 3.0: "Every 3 s"}


def reading_card() -> None:
    with ui.element("section").classes("yt-card").mark("reading"):
        with ui.element("div").classes("yt-card-head"):
            ui.label("Reading").classes("yt-h2")
        with ui.element("div").classes("yt-card-body"):
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Reader").classes("yt-setting-name")
                engines = ui.element("div").classes("yt-seg").mark("reading-engines")
            ui.label(
                "RapidOCR read real chat best, English and German. Windows OCR is the backup."
            ).classes("yt-hint")
            switch("Use GPU for OCR", config.ocr_gpu(), lambda on: choose_gpu(on)).mark(
                "reading-gpu"
            )
            gpu_status = ui.label().classes("yt-meta").mark("reading-gpu-status")
            ui.label(
                "RapidOCR on your graphics card: about a quarter of the CPU per read. Off by "
                "default, because the game uses that card too."
            ).classes("yt-hint")
            with ui.element("div").classes("yt-row yt-filters"):
                ui.label("Read the chat").classes("yt-setting-name")
                gaps = ui.element("div").classes("yt-seg").mark("reading-gaps")
            ui.label(
                "Every 3 s is lighter on the CPU, but a fast burst of chat can push a line out "
                "of the box before I read it."
            ).classes("yt-hint")

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

    def choose_engine(name: str) -> None:
        config.save_ocr_engine(name)
        render()

    def choose_gap(seconds: float) -> None:
        config.save_read_every_s(seconds)
        if runtime.reader is not None:
            runtime.reader.min_gap_s = seconds  # the next read already waits this long
        render()

    def choose_gpu(on: bool) -> None:
        config.save_ocr_gpu(on)
        ocr.use_gpu(on)
        show_gpu()

    def show_gpu() -> None:
        gpu_status.set_text(ocr.gpu_status())

    ui.timer(2.0, show_gpu)  # it changes with the next read, or if the card stops working
    show_gpu()

    def render() -> None:
        missing = [name for name in ocr.LABELS if name not in ocr.available()]
        segment(engines, ocr.LABELS, config.ocr_engine(), choose_engine, "engine", missing)
        segment(gaps, _GAPS, config.read_every_s(), choose_gap, "gap")

    render()
