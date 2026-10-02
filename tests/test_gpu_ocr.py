"""Use GPU for OCR (#208): off by default, falls back to the CPU by itself, says where it reads."""

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import config, gpu
from yaptracker.ocr import engine as ocr
from yaptracker.ui import shell


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(ocr, "_cache", {})
    monkeypatch.setattr(ocr, "_gpu_problem", None)
    monkeypatch.setattr(ocr, "_gpu_name", None)
    yield
    ocr.use_gpu(False)


class FakeEngine:
    def __init__(self, label, fail=False):
        self.label, self.fail, self.reads = label, fail, 0

    def read(self, image, accents=False, scale=2.0):
        self.reads += 1
        if self.fail:
            raise RuntimeError("device removed")
        return [self.label]

    def read_line(self, image):
        return self.label


def test_off_by_default_and_the_cpu_engine_is_used():
    assert config.ocr_gpu() is False
    assert ocr.gpu_status() == "Reading on the CPU."


def test_no_dedicated_card_means_cpu_and_says_why(monkeypatch):
    monkeypatch.setattr(gpu, "dedicated", lambda: None)
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda: FakeEngine("cpu"))
    ocr.use_gpu(True)
    assert ocr.get("rapidocr").read(None) == ["cpu"]
    assert (
        ocr.gpu_status()
        == "Reading on the CPU: the graphics card isn't there (no dedicated GPU found)."
    )


def test_a_card_that_fails_mid_evening_hands_over_to_the_cpu(monkeypatch):
    card = gpu.Adapter(0, "NVIDIA GeForce RTX 4090", 24 * 1024**3)
    monkeypatch.setattr(gpu, "dedicated", lambda: card)
    failing = FakeEngine("gpu", fail=True)
    monkeypatch.setattr(ocr, "RapidOcrEngine", lambda device=None: failing)
    monkeypatch.setitem(ocr.ENGINES, "rapidocr", lambda: FakeEngine("cpu"))
    ocr.use_gpu(True)
    engine = ocr.get("rapidocr")
    assert ocr.gpu_status() == "Reading on the NVIDIA GeForce RTX 4090."
    assert engine.read(None) == ["cpu"]  # the GPU read failed: this frame is read on the CPU
    assert engine.read(None) == ["cpu"] and failing.reads == 1  # and the GPU isn't tried again
    assert ocr.gpu_status().startswith("Reading on the CPU: the graphics card stopped working")


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


async def test_the_switch_in_settings(user: User, monkeypatch):
    config.save_setup_state("done")
    monkeypatch.setattr(gpu, "dedicated", lambda: None)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see("Reading on the CPU.")
    user.find(marker="reading-gpu").click()
    assert config.ocr_gpu() is True and ocr._gpu_wanted
    await user.should_see("Reading on the graphics card from the next chat line.")
