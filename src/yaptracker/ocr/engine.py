"""OCR engines behind one interface. RapidOCR is the default, Windows OCR the fallback (#11)."""

import contextlib
import logging
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from yaptracker.capture.source import Region

log = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """The engine can't run on this machine (e.g. Windows has no OCR language installed)."""


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float  # 0..1
    box: Region  # in chat-box pixels
    parts: tuple[tuple[str, Region], ...] = ()  # the words left to right, for icons between (#128)


UPSCALE = 2.0  # 1x drops the spaces between words; measured best at 1440p (#11)
REFERENCE_HEIGHT = 1440  # the window height UPSCALE was measured at


def upscale_for(window_height: int | None) -> float:
    """How much to enlarge a crop before OCR (#169): 2x at 1440p, and above 1440p just enough
    to give the text the same pixel height (4K: 1.33x). Overwatch's chat grows with the window,
    so a fixed 2x read 4K crops at 2.25x the pixels of 1440p: 3x the CPU, no better reading.
    Smaller windows keep 2x, as measured."""
    if not window_height or window_height <= REFERENCE_HEIGHT:
        return UPSCALE
    return UPSCALE * REFERENCE_HEIGHT / window_height


class OcrEngine(Protocol):
    def read(
        self, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        """Lines of text in a BGR image, top to bottom. Blocks: from UI code use run.io_bound.

        accents: look for ä/ç/é... even if the text doesn't look German (map names, #115).
        scale: enlarge the image this much first; upscale_for() the window height (#169).
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


def has_umlaut_dots(crop: np.ndarray) -> bool:
    """Two dots side by side right above one letter (ä ö ü), in a line crop (#247): the default
    model drops the dots, so its text can't tell; the picture can. Not the dots of "ii" (each
    sits on its own thin stem), not a colon (stacked), not quotes (no letter below)."""
    import cv2

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    text = cv2.bitwise_and(cv2.threshold(hsv[:, :, 2], 150, 1, cv2.THRESH_BINARY)[1],
                           cv2.threshold(hsv[:, :, 1], 70, 1, cv2.THRESH_BINARY)[1])  # fmt: skip
    count, _, stats, _ = cv2.connectedComponentsWithStats(text, connectivity=8)
    h = crop.shape[0]
    blobs = [tuple(int(v) for v in stats[i][:4]) for i in range(1, count) if stats[i][4] >= 2]
    dots = [b for b in blobs if b[2] <= 0.22 * h and b[3] <= 0.22 * h]
    bodies = [b for b in blobs if b[3] > 0.22 * h]
    for a in dots:
        for b in dots:
            gap = b[0] - (a[0] + a[2])
            if b[0] <= a[0] or not 0 <= gap <= 0.3 * h:
                continue
            if abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) > 0.1 * h:
                continue  # not side by side
            left, right, low = a[0], b[0] + b[2], max(a[1] + a[3], b[1] + b[3])
            if any(c[0] <= left + 1 and c[0] + c[2] >= right - 1 and 0 <= c[1] - low <= 0.25 * h
                   for c in bodies):  # fmt: skip
                return True
    return False


_PLAIN = str.maketrans("äöüÄÖÜ", "aouAOU")


def _runs(text: str) -> list[tuple[str, int]]:
    """'taaaat' -> [('t', 1), ('a', 4), ('t', 1)]."""
    runs: list[tuple[str, int]] = []
    for char in text:
        if runs and runs[-1][0] == char:
            runs[-1] = (char, runs[-1][1] + 1)
        else:
            runs.append((char, 1))
    return runs


def keep_repeats(default: str, latin: str) -> str:
    """The Latin model has the umlauts but squeezes repeated letters ("täääät" -> "tät", #247);
    the default model keeps every letter but drops the dots. Same letters run by run: the
    default's counts with the Latin's umlauts. Otherwise the Latin reading as it is."""
    ours, theirs = _runs(default), _runs(latin)
    plain = [(char.translate(_PLAIN), n) for char, n in theirs]
    if len(latin) >= len(default) or [c for c, _ in ours] != [c for c, _ in plain]:
        return latin
    return "".join(their[0] * our[1] for our, their in zip(ours, theirs, strict=True))


class _ReadTwice:
    """Recognition with both models on the same line crops (#118).

    The default model is best at English (it reads "I" and "o" where the Latin one sees "l" and
    "0", and skips the team icon), the Latin one has the umlauts. A line the Latin model reads
    with such letters is taken from it, every other line from the default model.
    """

    def __init__(self, default, latin) -> None:
        self.default, self._latin = default, latin
        self.always = threading.local()  # per thread: capture and the chat reader both read
        self.latin_reads = 0  # for the replay tool's numbers (#247)

    def __call__(self, crops, return_word_box: bool = False):
        ours, ours_s = self.default(crops, return_word_box)
        # German chat comes in conversations: one German-looking line and the whole chat box is
        # read again, names and system lines included ("You endorsed Björn!"). English-only
        # chat skips the second read (#115).
        # Or umlaut dots in the picture (#247): "täääätüüüü" reads as "taaaatuuuu", which
        # doesn't look German, so the text alone would never ask the Latin model.
        always = getattr(self.always, "on", False)
        if (not always and not any(looks_german(text) for text, _score in ours)
                and not any(has_umlaut_dots(crop) for crop in crops)):  # fmt: skip
            return ours, ours_s
        self.latin_reads += 1
        latin, latin_s = self._latin(crops, return_word_box)
        picked = [((keep_repeats(a[0], b[0]),) + tuple(b[1:])) if _has_accent(b[0]) else a
                  for a, b in zip(ours, latin, strict=True)]  # fmt: skip
        return picked, ours_s + latin_s


class RapidOcrEngine:
    """RapidOCR (ONNX, CPU) on the upscaled image (2x at 1440p) - 1x drops the spaces."""

    name = "rapidocr"
    label = "RapidOCR"

    def __init__(self, device: int | None = None) -> None:
        """`device`: a DXGI adapter index to run on with DirectML (#208), None for the CPU."""
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: loading the models takes ~1 s

        # One thread: by default onnxruntime spreads each read over every core and burns ~3x the
        # CPU doing it (measured, #108): a spike on all cores while the game is running.
        options = {"intra_op_num_threads": 1, "inter_op_num_threads": 1}
        if device is not None:
            options.update(det_use_dml=True, cls_use_dml=True, rec_use_dml=True)
        with _on_adapter(device):
            self._ocr = RapidOCR(**options)
            latin = RapidOCR(rec_model_path=str(LATIN_REC), rec_keys_path=str(LATIN_KEYS),
                             **options)  # fmt: skip
        if device is not None and self.provider() != "DmlExecutionProvider":
            raise OcrUnavailable("DirectML isn't in this build of onnxruntime")
        self._ocr.text_rec = _ReadTwice(self._ocr.text_rec, latin.text_rec)

    def provider(self) -> str:
        return self._ocr.text_det.infer.session.get_providers()[0]

    def read(
        self, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        import cv2

        big = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        self._ocr.text_rec.always.on = accents
        try:
            result, _ = self._ocr(big)
        finally:
            self._ocr.text_rec.always.on = False
        words = []
        for points, text, score in result or []:
            xs = [p[0] / scale for p in points]
            ys = [p[1] / scale for p in points]
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

    def __init__(self) -> None:
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine as WinOcr

        engine = WinOcr.try_create_from_language(Language("en-US"))
        if engine is None:
            engine = WinOcr.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("Windows has no OCR language installed")
        self._engine = engine

    def read(
        self, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        import asyncio

        return asyncio.run(self._read(image, scale))

    async def _read(self, image: np.ndarray, scale: float) -> list[OcrLine]:
        import cv2
        from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winsdk.windows.storage.streams import DataWriter

        big = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
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
                r.x / scale,
                r.y / scale,
                r.width / scale,
                r.height / scale,
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
_RAPID = RapidOcrEngine.name  # the engine that can run on the graphics card (#208)


def available() -> list[str]:
    return [name for name in ENGINES if name != WindowsOcrEngine.name or sys.platform == "win32"]


_cache: dict[str, OcrEngine] = {}
_cache_lock = threading.Lock()  # capture (signals) and the chat reader may both ask first


@contextlib.contextmanager
def _on_adapter(device: int | None):
    """RapidOCR gives DirectML no device_id, so it runs on adapter 0, which can be an iGPU:
    while its sessions are made, ask for the chosen adapter (#208)."""
    if device is None:
        yield
        return
    from rapidocr_onnxruntime.utils import infer_engine

    original = infer_engine.OrtInferSession._get_ep_list

    def with_device(session):
        return [(ep, {**opts, "device_id": device}) if ep == "DmlExecutionProvider" else (ep, opts)
                for ep, opts in original(session)]  # fmt: skip

    infer_engine.OrtInferSession._get_ep_list = with_device
    try:
        yield
    finally:
        infer_engine.OrtInferSession._get_ep_list = original


class _GpuOrCpu:
    """RapidOCR on the graphics card, and on the CPU as soon as that fails once (#208)."""

    name, label = RapidOcrEngine.name, RapidOcrEngine.label

    def __init__(self, gpu: OcrEngine, cpu: Callable[[], OcrEngine]) -> None:
        self._gpu, self._cpu = gpu, cpu

    def _call(self, method: str, *args, **kwargs):
        global _gpu_problem
        if self._gpu is not None:
            try:
                return getattr(self._gpu, method)(*args, **kwargs)
            except Exception as error:  # e.g. a driver reset: carry on on the CPU, and say so
                log.warning("OCR on the graphics card failed, back to the CPU: %s", error)
                self._gpu, _gpu_problem = None, f"stopped working ({error})"
        return getattr(self._cpu(), method)(*args, **kwargs)

    def read(self, image, accents=False, scale=UPSCALE):
        return self._call("read", image, accents=accents, scale=scale)

    def read_line(self, image):
        return self._call("read_line", image)


_gpu_problem: str | None = None  # why OCR isn't on the graphics card (#208, parked by #219)
_gpu_name: str | None = None


def _gpu_engine() -> OcrEngine:
    """The GPU RapidOCR (made once), or the CPU one with the reason kept.

    Not reachable since #219: on both test PCs it made Overwatch stutter or freeze. Kept for a
    later version with a low-priority GPU queue (see the parked issue)."""
    global _gpu_problem, _gpu_name
    if "rapidocr-gpu" not in _cache:
        from yaptracker import gpu

        card, engine = gpu.dedicated(), None
        if card is None:
            _gpu_problem = "isn't there (no dedicated GPU found)"
        else:
            try:
                engine = RapidOcrEngine(device=card.index)
                _gpu_name, _gpu_problem = card.name, None
                log.info("OCR on %s (DirectML, adapter %d)", card.name, card.index)
            except Exception as error:
                _gpu_problem = f"can't be used ({error})"
                log.warning("OCR can't use %s, reading on the CPU: %s", card.name, error)
        _cache["rapidocr-gpu"] = _GpuOrCpu(engine, _cpu_rapidocr)
    return _cache["rapidocr-gpu"]


def _cpu_rapidocr() -> OcrEngine:
    return get(_RAPID)


_making: dict[str, threading.Event] = {}  # engines being made right now, by name


def get(name: str) -> OcrEngine:
    """The engine, made once. Blocks while it's being made (~1 s): only from threads that may
    wait (the chat reader, io_bound UI code). The lock is never held while a model loads (#219),
    so ready() stays instant for the capture thread."""
    while True:
        with _cache_lock:
            if name in _cache:
                return _cache[name]
            making = _making.get(name)
            if making is None:
                making = _making[name] = threading.Event()
                mine = True
            else:
                mine = False
        if not mine:
            making.wait()
            continue  # made by the other thread, or it failed: then try here (and raise)
        try:
            engine = ENGINES[name]()
            with _cache_lock:
                _cache[name] = engine
            return engine
        finally:
            with _cache_lock:
                _making.pop(name, None)
            making.set()


def ready(name: str) -> OcrEngine | None:
    """The engine if it's made, else None at once (and it gets made in the background).
    For the capture thread: a match signal can miss a second, the capture can't stall (#219)."""
    with _cache_lock:
        if name in _cache:
            return _cache[name]
        busy = name in _making
    if not busy:
        warm_up(name)
    return None


def warm_up(name: str) -> None:
    """Make the engine in a background thread, so nobody waits for it later."""

    def make() -> None:
        try:
            get(name)
        except Exception as error:  # e.g. Windows OCR without a language: the reader says so
            log.warning("OCR engine %s can't start: %s", name, error)

    threading.Thread(target=make, name=f"load OCR {name}", daemon=True).start()
