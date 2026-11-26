"""The chat-trained engine (#624, #627): the model file fits its dictionary and reads, chat
reads go to the trained recognizer, match signals never do."""

import threading

import numpy as np
import onnxruntime
import pytest

from yaptracker import config, demo
from yaptracker.capture.source import default_chat_region
from yaptracker.ocr import engine as ocr


@pytest.fixture(scope="module")
def engine():
    return ocr.ChatTrainedOcrEngine()


def _demo_chat() -> np.ndarray:
    image = demo.screenshot()
    r = default_chat_region(image.width, image.height)
    crop = np.asarray(image.crop((r.x, r.y, r.x + r.width, r.y + r.height)))
    return np.ascontiguousarray(crop[:, :, ::-1])


def test_the_model_file_fits_its_dictionary():
    """RapidOCR decodes class k as line k of the dictionary (0 = blank, last = space): a file
    with other classes than the dictionary has lines would read every letter as another."""
    lines = ocr.CHAT_KEYS.read_text(encoding="utf-8").split("\n")
    assert lines[-1] == ""  # ends with a newline, no empty character in between
    session = onnxruntime.InferenceSession(str(ocr.CHAT_REC), providers=["CPUExecutionProvider"])
    out = session.run(None, {"x": np.zeros((1, 3, 48, 320), dtype=np.float32)})[0]
    assert out.shape[2] == len(lines) - 1 + 2
    assert ocr.CHAT_REC.stat().st_size < 12_000_000  # pruned: the unpruned export is 57 MB


def test_it_reads_the_demo_chat(engine):
    text = " / ".join(line.text for line in engine.read(_demo_chat()))
    assert "[NoodleBonk]: WAHOOOO" in text
    assert "SirPeelsALot (Reinhardt): Group up!" in text


class _Counting:
    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, 0

    def __call__(self, crops, return_word_box: bool = False):
        self.calls += 1
        return self.inner(crops, return_word_box)


@pytest.fixture
def counted(engine, monkeypatch):
    slot = engine._ocr.text_rec
    chat, default, latin = (_Counting(m) for m in (slot._chat, slot.default, slot._stock._latin))
    monkeypatch.setattr(slot, "_chat", chat)
    monkeypatch.setattr(slot, "default", default)  # what read_line asks for
    monkeypatch.setattr(slot._stock, "default", default)
    monkeypatch.setattr(slot._stock, "_latin", latin)
    return chat, default, latin


def test_a_chat_read_goes_to_the_trained_recognizer_only(engine, counted):
    chat, default, latin = counted
    assert engine.read(_demo_chat())
    assert chat.calls == 1
    assert default.calls == latin.calls == 0  # one read, no second (Latin) one


def test_match_signals_never_reach_the_trained_recognizer(engine, counted):
    chat, default, latin = counted
    image = _demo_chat()
    engine.read_line(image[:60])  # a signal strip (VICTORY, the queue title)
    assert engine.read(image, accents=True)  # the hero-select corner: map names
    assert chat.calls == 0
    assert default.calls == 2 and latin.calls == 1


def test_a_signal_read_in_one_thread_leaves_a_chat_read_in_another_alone(engine, counted):
    """Capture reads signals while the chat reader reads chat, on one engine object (#219)."""
    chat, _default, _latin = counted
    slot, seen = engine._ocr.text_rec, []
    slot.always.on = True  # this thread is in the middle of a hero-select read

    def chat_read() -> None:
        seen.append(getattr(slot.always, "on", False))
        engine.read(_demo_chat())

    reader = threading.Thread(target=chat_read)
    reader.start()
    reader.join()
    slot.always.on = False
    assert seen == [False] and chat.calls == 1


def test_it_can_be_chosen_and_rapidocr_stays_the_default(tmp_path):
    path = tmp_path / "config.json"
    assert config.ocr_engine(path) == "rapidocr" == ocr.DEFAULT
    assert "chat" in ocr.available() and ocr.LABELS["chat"] == "Chat-trained"
    config.save_ocr_engine("chat", path)
    assert config.ocr_engine(path) == "chat"
