"""'What I can read': the chat-box crop and the lines OCR finds in it (#12)."""

import numpy as np
from nicegui import background_tasks, run, ui
from PIL import Image

from yaptracker import channels, config
from yaptracker.ocr import engine as ocr
from yaptracker.parser import ChatLine, parse

LOW_CONFIDENCE = 0.8
YAP_KINDS = {"message", "comms", "system"}
# Label and colour class per line; typed chat gets its team/match colour from #14.
_CHIPS = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}
_IGNORED = {"input": "Input line", "cut": "Cut off"}


def _chip(line: ChatLine) -> tuple[str, str]:
    if line.kind in _IGNORED:
        return _IGNORED[line.kind], "yt-ch-ignored"
    if line.channel in _CHIPS:
        return _CHIPS[line.channel], f"yt-ch-{line.channel}"
    return ("Chat", "yt-ch-chat") if line.kind == "message" else ("?", "yt-ch-unknown")


class ReadPreview:
    def __init__(self) -> None:
        self._image: Image.Image | None = None
        self._request = 0
        self.learned_colours: dict[str, float] = {}  # channel hues this screenshot proves
        with ui.element("section").classes("yt-card"), ui.element("div").classes("yt-card-body"):
            with ui.element("div").classes("yt-row"):
                ui.label("What I can read").classes("yt-h2")
                ui.element("div").classes("yt-grow")
                self._count = ui.label().classes("yt-chip yt-chip--ok yt-hidden").mark("line-count")
            self._crop = ui.image().classes("yt-crop").props("no-spinner no-transition")
            self._info = ui.label().classes("yt-meta").mark("crop-info")
            self._engines = ui.element("div").classes("yt-seg")
            self._lines = ui.element("div").classes("yt-read-lines").mark("read-lines")
        self._render_engines()

    def show(self, crop: Image.Image, info: str) -> None:
        self._image = crop
        self._crop.set_source(crop)
        self._info.set_text(info)
        background_tasks.create(self._read(), name="ocr preview")

    def _render_engines(self) -> None:
        chosen, available = config.ocr_engine(), ocr.available()
        self._engines.clear()
        with self._engines:
            for name, label in ocr.LABELS.items():
                b = ui.element("button").classes("yt-seg-item").props('type="button"')
                b.mark(f"engine-{name}")
                if name == chosen:
                    b.classes(add="is-active").props('aria-pressed="true"')
                if name not in available:
                    b.props('disabled title="Windows only"')
                with b:
                    ui.label(label)
                b.on("click", lambda name=name: self._choose(name))

    def _choose(self, name: str) -> None:
        config.save_ocr_engine(name)
        self._render_engines()
        if self._image is not None:
            background_tasks.create(self._read(), name="ocr preview")

    async def _read(self) -> None:
        self._request += 1
        request, name = self._request, config.ocr_engine()
        bgr = np.ascontiguousarray(np.asarray(self._image)[:, :, ::-1])
        self._set_hint("Reading...")
        try:
            lines = await run.io_bound(lambda: ocr.get(name).read(bgr))
        except Exception as error:  # shown in the card, not swallowed: e.g. no OCR language
            if request == self._request:
                self._set_hint(f"{ocr.LABELS[name]} didn't work here: {error}")
            raise
        if request != self._request:
            return  # the box moved again while this read was running
        chat = channels.assign(parse(lines), bgr, config.channel_colours())
        self.learned_colours = channels.learn(chat, bgr)
        yaps = sum(line.kind in YAP_KINDS for line in chat)
        self._count.set_text(f"{yaps} yaps")
        self._count.classes(remove="yt-hidden")
        self._lines.clear()
        with self._lines:
            if not chat:
                ui.label("Nothing readable in the box. Is the chat inside it?").classes("yt-hint")
            for line in chat:
                self._render(line)

    def _render(self, line: ChatLine) -> None:
        label, colour = _chip(line)
        ignored = " is-ignored" if line.kind in _IGNORED else ""
        with ui.element("div").classes("yt-read-line" + ignored):
            ui.label(label).classes(f"yt-read-chip {colour}")
            with ui.element("div").classes("yt-read-text"):
                if line.speaker and line.kind != "system":
                    who = line.speaker + (f" ({line.hero})" if line.hero else "")
                    who += f" to {line.target}" if line.target else ""
                    ui.label(who + ":").classes(f"yt-read-speaker {colour}")
                ui.label(line.text).classes("yt-read-message")
            low = " yt-conf--low" if line.confidence < LOW_CONFIDENCE else ""
            ui.label(f"{line.confidence:.0%}").classes("yt-conf" + low)

    def _set_hint(self, text: str) -> None:
        self._count.classes(add="yt-hidden")
        self._lines.clear()
        with self._lines:
            ui.label(text).classes("yt-hint")
