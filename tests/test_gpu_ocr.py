"""GPU OCR is out of v1 (#219): no switch, a left-on setting is dropped, engines load in the
background and never under a lock the capture thread needs."""

import threading
import time

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, gpu, paths
from yaptracker.ocr import engine as ocr
from yaptracker.ui import shell


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(ocr, "_cache", {})
    monkeypatch.setattr(ocr, "_making", {})
    monkeypatch.setattr(ocr, "_gpu_problem", None)
    monkeypatch.setattr(ocr, "_gpu_name", None)


class FakeEngine:
    def __init__(self, label, fail=False, slow_s=0.0):
        time.sleep(slow_s)
        self.label, self.fail, self.reads = label, fail, 0

    def read(self, image, accents=False, scale=2.0):
        self.reads += 1
        if self.fail:
            raise RuntimeError("device removed")
        return [self.label]

    def read_line(self, image):
        return self.label


def test_a_gpu_setting_left_on_is_dropped_and_reading_stays_on_the_cpu(monkeypatch):
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('{"ocr_gpu": true, "read_every_s": 3.0}', encoding="utf-8")
    assert config.drop_ocr_gpu() is True
    assert config.drop_ocr_gpu() is False and config.read_every_s() == 3.0  # the rest stays
    card = gpu.Adapter(0, "NVIDIA GeForce RTX 4090", 24 * 1024**3)
    monkeypatch.setattr(gpu, "dedicated", lambda: card)
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda: FakeEngine("cpu"))
    assert ocr.get("rapidocr").read(None) == ["cpu"]  # a card is there; the CPU reads anyway


def test_a_model_loading_never_blocks_the_capture_thread(monkeypatch):
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda: FakeEngine("cpu", slow_s=0.5))
    started = time.monotonic()
    assert ocr.ready("rapidocr") is None  # not made yet: the capture skips this tick
    assert ocr.ready("rapidocr") is None  # and doesn't start a second one
    assert time.monotonic() - started < 0.1
    got = []
    reader = threading.Thread(target=lambda: got.append(ocr.get("rapidocr")))  # may wait
    reader.start()
    reader.join(5)
    assert got and ocr.ready("rapidocr") is got[0]  # one engine, made once


def test_an_engine_that_fails_to_load_raises_for_who_waits(monkeypatch):
    def broken():
        raise ocr.OcrUnavailable("Windows has no OCR language installed")

    monkeypatch.setitem(ocr.ENGINES, "windows", broken)
    with pytest.raises(ocr.OcrUnavailable):
        ocr.get("windows")
    assert ocr.ready("windows") is None  # and the capture just skips


def test_the_parked_gpu_engine_still_falls_back_to_the_cpu(monkeypatch):
    """The DirectML code stays for later (#219): if it's ever used again, a failing card hands
    over to the CPU after one failed read."""
    card = gpu.Adapter(0, "NVIDIA GeForce RTX 4090", 24 * 1024**3)
    monkeypatch.setattr(gpu, "dedicated", lambda: card)
    failing = FakeEngine("gpu", fail=True)
    monkeypatch.setattr(ocr, "RapidOcrEngine", lambda device=None: failing)
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda: FakeEngine("cpu"))
    engine = ocr._gpu_engine()
    assert engine.read(None) == ["cpu"] and engine.read(None) == ["cpu"] and failing.reads == 1


def test_the_dedicated_card_is_the_one_with_its_own_memory(monkeypatch):
    cards = [gpu.Adapter(0, "AMD Radeon(TM) Graphics", 512 * 1024**2),
             gpu.Adapter(1, "NVIDIA GeForce RTX 4090", 24 * 1024**3)]  # fmt: skip
    monkeypatch.setattr(gpu, "adapters", lambda: cards)
    assert gpu.dedicated().index == 1
    monkeypatch.setattr(gpu, "adapters", lambda: cards[:1])
    assert gpu.dedicated() is None  # an iGPU alone doesn't count (#126)


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_has_no_gpu_switch(user: User):
    config.save_setup_state("done")
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Read the chat")
    await user.should_not_see("Use GPU for OCR")
