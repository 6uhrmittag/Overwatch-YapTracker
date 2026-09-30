"""OCR engines behind one interface. RapidOCR is the default, Windows OCR the fallback (#11)."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from yaptracker.capture.source import Region


class OcrUnavailable(RuntimeError):
    """The engine can't run on this machine (e.g. Windows has no OCR language installed)."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float  # 0..1
    box: Region  # in chat-box pixels


class OcrEngine(Protocol):
    def read(self, image: np.ndarray) -> list[OcrLine]:
        """Lines of text in a BGR image, top to bottom. Blocks: from UI code use run.io_bound."""
        ...


@dataclass
class _Word:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


def group_lines(words: list[_Word]) -> list[OcrLine]:
    """Words whose vertical centres are within half a word height form one visual line."""
    lines: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: w.y + w.height / 2):
        centre = word.y + word.height / 2
        if lines:
            last = lines[-1][0]
            if abs(centre - (last.y + last.height / 2)) < last.height / 2:
                lines[-1].append(word)
                continue
        lines.append([word])
    result = []
    for line in lines:
        line.sort(key=lambda w: w.x)
        x0, y0 = min(w.x for w in line), min(w.y for w in line)
        x1 = max(w.x + w.width for w in line)
        y1 = max(w.y + w.height for w in line)
        result.append(
            OcrLine(
                text=" ".join(w.text for w in line),
                confidence=sum(w.confidence for w in line) / len(line),
                box=Region(round(x0), round(y0), round(x1 - x0), round(y1 - y0)),
            )
        )
    return result


class RapidOcrEngine:
    """RapidOCR (ONNX, CPU) on the 2x upscaled image - 1x drops the spaces between words."""

    name = "rapidocr"
    label = "RapidOCR"
    scale = 2.0

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: loading the models takes ~1 s

        self._ocr = RapidOCR()

    def read(self, image: np.ndarray) -> list[OcrLine]:
        import cv2

        big = cv2.resize(image, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_CUBIC)
        result, _ = self._ocr(big)
        words = []
        for points, text, score in result or []:
            xs = [p[0] / self.scale for p in points]
            ys = [p[1] / self.scale for p in points]
            words.append(
                _Word(text, float(score), min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            )
        return group_lines(words)


class WindowsOcrEngine:
    """Windows.Media.Ocr via winsdk: ~10x faster, but loses lines on bright backgrounds (#11)."""

    name = "windows"
    label = "Windows OCR"
    scale = 2.0

    def __init__(self) -> None:
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine as WinOcr

        engine = WinOcr.try_create_from_language(Language("en-US"))
        if engine is None:
            engine = WinOcr.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("Windows has no OCR language installed")
        self._engine = engine

    def read(self, image: np.ndarray) -> list[OcrLine]:
        import asyncio

        return asyncio.run(self._read(image))

    async def _read(self, image: np.ndarray) -> list[OcrLine]:
        import cv2
        from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winsdk.windows.storage.streams import DataWriter

        big = cv2.resize(image, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_CUBIC)
        bgra = cv2.cvtColor(big, cv2.COLOR_BGR2BGRA)
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, bgra.shape[1], bgra.shape[0]
        )
        result = await self._engine.recognize_async(bitmap)
        words = [
            _Word(
                w.text,
                1.0,
                r.x / self.scale,
                r.y / self.scale,
                r.width / self.scale,
                r.height / self.scale,
            )  # fmt: skip
            for line in result.lines
            for w in line.words
            for r in [w.bounding_rect]
        ]
        # Windows OCR reports no confidence; 1.0 means "unknown", not "certain".
        return group_lines(words)


ENGINES: dict[str, Callable[[], OcrEngine]] = {
    RapidOcrEngine.name: RapidOcrEngine,
    WindowsOcrEngine.name: WindowsOcrEngine,
}
LABELS = {RapidOcrEngine.name: RapidOcrEngine.label, WindowsOcrEngine.name: WindowsOcrEngine.label}
DEFAULT = RapidOcrEngine.name


def available() -> list[str]:
    return [name for name in ENGINES if name != WindowsOcrEngine.name or sys.platform == "win32"]


_cache: dict[str, OcrEngine] = {}


def get(name: str) -> OcrEngine:
    """Engines are expensive to create, so each one is made once."""
    if name not in _cache:
        _cache[name] = ENGINES[name]()
    return _cache[name]
