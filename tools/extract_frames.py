"""Turn an OBS recording into replay frames (#62).

    python tools/extract_frames.py RECORDING.mkv [--from mm:ss] [--to mm:ss] [--threads 2]

Writes fixtures/private/frames/<recording name>/:
  chat/<ms>.png   chat region, 4 fps (plays at real timing with ReplayFrameSource)
  full/<ms>.jpg   whole frame, 1 fps (hero select, VICTORY/DEFEAT detection)
  index.json      source, resolution, region, fps, frame counts

Heavy: decodes the whole video. Run it when nobody is playing. Nothing here is ever committed.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from yaptracker.capture.source import Region, default_chat_region

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "fixtures" / "private" / "frames"
CHAT_FPS = 4
FULL_FPS = 1
# Zero-padded so name order is time order (7 digits = up to 2.7 hours).
MS_DIGITS = 7


def parse_time(text: str) -> float:
    """'mm:ss', 'hh:mm:ss' or plain seconds -> seconds."""
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def probe(recording: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(recording)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    info = json.loads(out)
    stream = info["streams"][0]
    return stream["width"], stream["height"], float(info["format"]["duration"])


def ffmpeg_command(
    recording: Path, out: Path, region: Region, start: float, end: float | None, threads: int
) -> list[str]:
    cut = ["-ss", f"{start:.3f}"] + (["-to", f"{end:.3f}"] if end is not None else [])
    graph = (
        f"[0:v]split=2[a][b];"
        f"[a]fps={CHAT_FPS},crop={region.width}:{region.height}:{region.x}:{region.y}[chat];"
        f"[b]fps={FULL_FPS}[full]"
    )
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-threads", str(threads),
        *cut, "-i", str(recording),
        "-filter_complex", graph, "-filter_complex_threads", str(threads),
        "-map", "[chat]", str(out / "chat" / "%07d.png"),
        "-map", "[full]", "-q:v", "3", str(out / "full" / "%07d.jpg"),
    ]  # fmt: skip


def rename_to_ms(folder: Path, fps: int, offset: float) -> int:
    """ffmpeg numbers frames 1, 2, 3...; frame n of an fps filter sits at (n - 1) / fps."""
    frames = sorted(folder.iterdir())
    for path in frames:
        ms = round((offset + (int(path.stem) - 1) / fps) * 1000)
        path.rename(path.with_name(f"{ms:0{MS_DIGITS}d}{path.suffix}"))
    return len(frames)


def extract(
    recording: Path,
    out_root: Path = OUT_ROOT,
    start: float = 0.0,
    end: float | None = None,
    threads: int = 2,
) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        sys.exit("ffmpeg is missing. Install it with: sudo apt install ffmpeg")
    width, height, duration = probe(recording)
    region = default_chat_region(width, height)
    out = out_root / recording.stem
    if out.exists():
        shutil.rmtree(out)
    (out / "chat").mkdir(parents=True)
    (out / "full").mkdir()
    subprocess.run(ffmpeg_command(recording, out, region, start, end, threads), check=True)
    index = {
        "source": str(recording),
        "resolution": [width, height],
        "duration_s": duration,
        "from_s": start,
        "to_s": end,
        "chat": {
            "fps": CHAT_FPS,
            "region": [region.x, region.y, region.width, region.height],
            "frames": rename_to_ms(out / "chat", CHAT_FPS, start),
        },
        "full": {"fps": FULL_FPS, "frames": rename_to_ms(out / "full", FULL_FPS, start)},
    }
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("recording", type=Path)
    parser.add_argument("--from", dest="start", default="0", help="mm:ss (default: start)")
    parser.add_argument("--to", dest="end", help="mm:ss (default: end of file)")
    parser.add_argument("--threads", type=int, default=2, help="ffmpeg threads (keep low in game)")
    parser.add_argument("--out", type=Path, default=OUT_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    end = parse_time(args.end) if args.end else None
    out = extract(args.recording, args.out, parse_time(args.start), end, args.threads)
    index = json.loads((out / "index.json").read_text())
    print(f"{out}: {index['chat']['frames']} chat frames, {index['full']['frames']} full frames")


if __name__ == "__main__":
    main()
