import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from yaptracker.capture.replay import ReplayFrameSource
from yaptracker.capture.source import Region, default_chat_region

_spec = importlib.util.spec_from_file_location(
    "extract_frames", Path(__file__).parents[1] / "tools" / "extract_frames.py"
)
extract_frames = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_frames)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_default_chat_region_scales_from_1440p():
    assert default_chat_region(2560, 1440) == Region(55, 510, 615, 395)
    assert default_chat_region(1920, 1080) == Region(41, 382, 461, 296)


@pytest.mark.parametrize(("text", "seconds"), [("90", 90), ("1:30", 90), ("1:02:03", 3723)])
def test_parse_time(text, seconds):
    assert extract_frames.parse_time(text) == seconds


@needs_ffmpeg
def test_extracts_chat_and_full_frames_with_ms_names(tmp_path):
    video = tmp_path / "2026-01-01_20-00-00.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=3",
         "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )  # fmt: skip
    out = extract_frames.extract(video, tmp_path / "frames", start=1.0, threads=1)

    assert out == tmp_path / "frames" / "2026-01-01_20-00-00"
    chat = sorted(p.name for p in (out / "chat").iterdir())
    assert chat[:3] == ["0001000.png", "0001250.png", "0001500.png"]
    assert len(chat) == 8  # 2 s at 4 fps
    assert sorted(p.name for p in (out / "full").iterdir()) == ["0001000.jpg", "0002000.jpg"]

    index = json.loads((out / "index.json").read_text())
    assert index["resolution"] == [1280, 720]
    assert index["chat"]["region"] == [28, 255, 308, 198]  # default region scaled to 720p

    frames = list(ReplayFrameSource(out / "chat").frames())
    assert [f.ts for f in frames[:3]] == [0.0, 0.25, 0.5]
    assert frames[0].image.shape == (198, 308, 3)
