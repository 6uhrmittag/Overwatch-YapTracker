"""Windows OCR only runs on Windows; CI runs this file on the Windows runner."""

import sys

import pytest

from tests.test_ocr import demo_chat_crop
from yaptracker.ocr import engine as ocr

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR needs Windows")


def test_windows_ocr_reads_the_demo_chat():
    try:
        engine = ocr.get("windows")
    except ocr.OcrUnavailable as reason:
        pytest.skip(str(reason))
    text = " ".join(line.text for line in engine.read(demo_chat_crop()))
    assert "WAHOO" in text.upper()


def test_rapidocr_on_directml_reads_like_the_cpu():
    """#208: the GPU engine reads the same. CI's runner only has the software adapter, which
    DirectML can run on too; on a real PC it's the dedicated card."""
    import onnxruntime

    if "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        pytest.skip("this onnxruntime has no DirectML")
    try:
        engine = ocr.RapidOcrEngine(device=0)
    except Exception as error:  # e.g. no D3D12 device on this runner
        pytest.skip(f"DirectML can't start here: {error}")
    assert engine.provider() == "DmlExecutionProvider"
    expected = [line.text for line in ocr.get("rapidocr").read(demo_chat_crop())]
    assert [line.text for line in engine.read(demo_chat_crop())] == expected


def test_the_dedicated_gpu_is_never_a_software_adapter():
    from yaptracker import gpu

    card = gpu.dedicated()
    assert card is None or card.dedicated >= gpu.MIN_DEDICATED  # CI: no real card, so None
