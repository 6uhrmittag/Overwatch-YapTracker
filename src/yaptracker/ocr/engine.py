"""OCR engines behind one interface. RapidOCR is the default, Windows OCR the fallback (#11)."""

import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
    parts: tuple[tuple[str, Region], ...] = ()  # the words left to right, for icons between (#128)


class OcrEngine(Protocol):
    def read(self, image: np.ndarray, accents: bool = False) -> list[OcrLine]:
        """Lines of text in a BGR image, top to bottom. Blocks: from UI code use run.io_bound.

        accents: look for ä/ç/é... even if the text doesn't look German (map names, #115).
        """
        ...

    def read_line(self, image: np.ndarray) -> str:
        """The text of an image that holds exactly one line (a signal strip, #93). Fast."""
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
                parts=tuple(
                    (w.text, Region(round(w.x), round(w.y), round(w.width), round(w.height)))
                    for w in line
                ),
            )
        )
    return result


# Recognition model with a Latin alphabet (#118): the default one has no ä ö ü ß é at all.
_MODELS = Path(__file__).parent / "models"
LATIN_REC = _MODELS / "latin_PP-OCRv5_rec_mobile.onnx"
LATIN_KEYS = _MODELS / "ppocrv5_latin_dict.txt"


def _has_accent(text: str) -> bool:
    return any(ord(c) > 127 and c.isalpha() for c in text)


# A line the default model read looks German (#115, Marv's decision): only then does the Latin
# model read it again. The default model has no ä ö ü ß, so it writes "GruBe", "Suf", "fur",
# "Ubermorgen". A false alarm (e.g. a CamelCase name like "M00dyBl4e") only costs a read.
_SHARP_S = re.compile(r"[a-z]B(?:e|t|en|er|es|\b)|eib|\b(?:Gru|Gro|Su|Fu|Spa|wei|hei)f\b")
_GERMAN_WORDS = (
    "und ich nicht schon mal aber ist das der den dem ein eine einen du wir ihr bin bist auch "
    "noch gut ja nein bitte danke hallo jetzt wo wie wer warum hier dann doch mit von zu auf "
    "aus bei bis nach vor oder wenn weil sehr viel gerne spiel spielen heiler heile heilen "
    "gegner leute jungs wieder gott alle alles klar euch "
    # as the default model spells them, without umlauts
    "fur uber ubel uberall ubermorgen arger ol schone grune mude konnen mussen spater wurde "
    "ware hatte nachste mochte tschuss osterreich grusse"
)
_GERMAN = frozenset(_GERMAN_WORDS.split())
_WORDS = re.compile(r"[A-Za-z]+")


def looks_german(text: str) -> bool:
    return bool(_SHARP_S.search(text)) or any(w.lower() in _GERMAN for w in _WORDS.findall(text))


class _ReadTwice:
    """Recognition with both models on the same line crops (#118).

    The default model is best at English (it reads "I" and "o" where the Latin one sees "l" and
    "0", and skips the team icon), the Latin one has the umlauts. A line the Latin model reads
    with such letters is taken from it, every other line from the default model.
    """

    def __init__(self, default, latin) -> None:
        self.default, self._latin = default, latin
        self.always = threading.local()  # per thread: capture and the chat reader both read

    def __call__(self, crops, return_word_box: bool = False):
        ours, ours_s = self.default(crops, return_word_box)
        # German chat comes in conversations: one German-looking line and the whole chat box is
        # read again, names and system lines included ("You endorsed Björn!"). English-only
        # chat skips the second read (#115).
        always = getattr(self.always, "on", False)
        if not always and not any(looks_german(text) for text, _score in ours):
            return ours, ours_s
        latin, latin_s = self._latin(crops, return_word_box)
        picked = [b if _has_accent(b[0]) else a for a, b in zip(ours, latin, strict=True)]
        return picked, ours_s + latin_s


class RapidOcrEngine:
    """RapidOCR (ONNX, CPU) on the 2x upscaled image - 1x drops the spaces between words."""

    name = "rapidocr"
    label = "RapidOCR"
    scale = 2.0

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: loading the models takes ~1 s

        # One thread: by default onnxruntime spreads each read over every core and burns ~3x the
        # CPU doing it (measured, #108): a spike on all cores while the game is running.
        one_thread = {"intra_op_num_threads": 1, "inter_op_num_threads": 1}
        self._ocr = RapidOCR(**one_thread)
        latin = RapidOCR(rec_model_path=str(LATIN_REC), rec_keys_path=str(LATIN_KEYS), **one_thread)
        self._ocr.text_rec = _ReadTwice(self._ocr.text_rec, latin.text_rec)

    def read(self, image: np.ndarray, accents: bool = False) -> list[OcrLine]:
        import cv2

        big = cv2.resize(image, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_CUBIC)
        self._ocr.text_rec.always.on = accents
        try:
            result, _ = self._ocr(big)
        finally:
            self._ocr.text_rec.always.on = False
        words = []
        for points, text, score in result or []:
            xs = [p[0] / self.scale for p in points]
            ys = [p[1] / self.scale for p in points]
            words.append(
                _Word(text, float(score), min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            )
        return group_lines(words)

    def read_line(self, image: np.ndarray) -> str:
        # Recognition only: text detection would scale a 60 px strip up to 736 px (~20x slower).
        # The default model alone: signal strips are English capitals (#93, #94).
        result, _ = self._ocr.text_rec.default(image)
        return " ".join(text for text, _score in result or [])


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

    def read(self, image: np.ndarray, accents: bool = False) -> list[OcrLine]:
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

    def read_line(self, image: np.ndarray) -> str:
        return " ".join(line.text for line in self.read(image))  # it's fast enough as it is


ENGINES: dict[str, Callable[[], OcrEngine]] = {
    RapidOcrEngine.name: RapidOcrEngine,
    WindowsOcrEngine.name: WindowsOcrEngine,
}
LABELS = {RapidOcrEngine.name: RapidOcrEngine.label, WindowsOcrEngine.name: WindowsOcrEngine.label}
DEFAULT = RapidOcrEngine.name


def available() -> list[str]:
    return [name for name in ENGINES if name != WindowsOcrEngine.name or sys.platform == "win32"]


_cache: dict[str, OcrEngine] = {}
_cache_lock = threading.Lock()  # capture (signals) and the chat reader may both ask first


def get(name: str) -> OcrEngine:
    """Engines are expensive to create, so each one is made once."""
    with _cache_lock:
        if name not in _cache:
            _cache[name] = ENGINES[name]()
        return _cache[name]
