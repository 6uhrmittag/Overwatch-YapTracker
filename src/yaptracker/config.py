"""User settings in data/config.json. Only what the user changed is stored; the rest is defaults."""

import json
from pathlib import Path

from yaptracker import paths
from yaptracker.capture.source import Region, default_chat_region
from yaptracker.ocr import engine as ocr


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _key(width: int, height: int) -> str:
    return f"{width}x{height}"


def saved_chat_regions(path: Path | None = None) -> dict[str, Region]:
    """Calibrated chat boxes by resolution, e.g. {"2560x1440": Region(...)}."""
    saved = _load(path or paths.config_file()).get("chat_regions", {})
    return {resolution: Region(**r) for resolution, r in saved.items()}


def saved_chat_region(width: int, height: int, path: Path | None = None) -> Region | None:
    return saved_chat_regions(path).get(_key(width, height))


def chat_region(width: int, height: int, path: Path | None = None) -> Region:
    """The calibrated chat box for this resolution, or the measured default."""
    return saved_chat_region(width, height, path) or default_chat_region(width, height)


def save_chat_region(width: int, height: int, region: Region, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data.setdefault("chat_regions", {})[_key(width, height)] = {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }
    _save(path, data)


def ocr_engine(path: Path | None = None) -> str:
    """The chosen OCR engine, if it runs on this OS; otherwise the default."""
    chosen = _load(path or paths.config_file()).get("ocr_engine", ocr.DEFAULT)
    return chosen if chosen in ocr.available() else ocr.DEFAULT


def save_ocr_engine(name: str, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["ocr_engine"] = name
    _save(path, data)
