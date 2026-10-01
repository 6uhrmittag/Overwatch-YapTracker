"""User settings in data/config.json. Only what the user changed is stored; the rest is defaults."""

import json
from dataclasses import asdict, dataclass
from math import gcd
from pathlib import Path

from yaptracker import __version__, paths
from yaptracker.capture.changes import ChangeDetector
from yaptracker.capture.source import Region, RelativeRegion, default_chat_region
from yaptracker.identity import Identity
from yaptracker.ocr import engine as ocr


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def aspect(width: int, height: int) -> str:
    """'16:9' for 2560x1440 and 1920x1080 alike: one calibration serves every size of a ratio."""
    d = gcd(width, height)
    return f"{width // d}:{height // d}"


def _chat_boxes(path: Path) -> dict:
    """Saved chat boxes by aspect ratio. Converts the old per-resolution pixels once (#84)."""
    data = _load(path)
    if "chat_regions" in data:  # before #84: {"2560x1440": {"x": 55, ...}} in pixels
        for size, r in data.pop("chat_regions").items():
            width, height = (int(n) for n in size.split("x"))
            box = RelativeRegion.from_pixels(Region(**r), width, height)
            data.setdefault("chat_boxes", {})[aspect(width, height)] = {
                **asdict(box),
                "calibrated_at": [width, height],
            }
        _save(path, data)
    return data.get("chat_boxes", {})


@dataclass(frozen=True)
class SavedChatBox:
    box: RelativeRegion
    calibrated_at: tuple[int, int]  # the window size it was drawn on


def saved_chat_boxes(path: Path | None = None) -> dict[str, SavedChatBox]:
    """Calibrated chat boxes by aspect ratio, e.g. {"16:9": SavedChatBox(...)}."""
    return {
        ratio: SavedChatBox(
            RelativeRegion(**{k: v for k, v in b.items() if k != "calibrated_at"}),
            tuple(b["calibrated_at"]),
        )  # fmt: skip
        for ratio, b in _chat_boxes(path or paths.config_file()).items()
    }


def chat_region(width: int, height: int, path: Path | None = None) -> Region:
    """The chat box in pixels for a window of this size: calibrated for its ratio, or default."""
    saved = saved_chat_boxes(path).get(aspect(width, height))
    return saved.box.to_pixels(width, height) if saved else default_chat_region(width, height)


def save_chat_region(width: int, height: int, region: Region, path: Path | None = None) -> None:
    path = path or paths.config_file()
    _chat_boxes(path)  # convert old entries first
    data = _load(path)
    box = RelativeRegion.from_pixels(region, width, height)
    data.setdefault("chat_boxes", {})[aspect(width, height)] = {
        **asdict(box),
        "calibrated_at": [width, height],
    }
    checked = set(data.get("checked_sizes", [])) | {f"{width}x{height}"}
    data["checked_sizes"] = sorted(checked)
    _save(path, data)


def size_needs_check(width: int, height: int, path: Path | None = None) -> bool:
    """One-time hint: Overwatch runs at a size the chat box wasn't drawn on (#84)."""
    path = path or paths.config_file()
    boxes = saved_chat_boxes(path)
    if not boxes or f"{width}x{height}" in _load(path).get("checked_sizes", []):
        return False
    saved = boxes.get(aspect(width, height))
    return saved is None or saved.calibrated_at != (width, height)


def mark_size_checked(width: int, height: int, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["checked_sizes"] = sorted(set(data.get("checked_sizes", [])) | {f"{width}x{height}"})
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


READ_GAPS = (1.5, 3.0)  # seconds between two reads of the chat box (#138, #152)


def read_every_s(path: Path | None = None) -> float:
    chosen = _load(path or paths.config_file()).get("read_every_s", READ_GAPS[0])
    return chosen if chosen in READ_GAPS else READ_GAPS[0]


def save_read_every_s(seconds: float, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["read_every_s"] = seconds
    _save(path, data)


HOTKEYS = {
    "pause": "Ctrl+Alt+P",  # auto-resumes at the next match
    "new_match": "Ctrl+Alt+M",  # manual override only; matches split themselves (#21)
    "lookup": "Ctrl+Alt+F",  # "Who's that?": YapTracker to the front, search focused (#27)
    "save": "Ctrl+Alt+S",  # optional: keep the last 20 s of chat as a debug sample (#110)
}


def hotkeys(path: Path | None = None) -> dict[str, str]:
    """Action -> combo, e.g. {"pause": "Ctrl+Alt+P", ...}; changed ones from Settings (#32)."""
    saved = _load(path or paths.config_file()).get("hotkeys", {})
    return {action: saved.get(action, combo) for action, combo in HOTKEYS.items()}


def save_hotkey(action: str, combo: str, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data.setdefault("hotkeys", {})[action] = combo
    _save(path, data)


def channel_colours(path: Path | None = None) -> dict[str, float]:
    """Text hue per channel as learned at calibration, e.g. {"team": 72.0, "system": 56.0}."""
    return _load(path or paths.config_file()).get("channel_colours", {})


def save_channel_colours(colours: dict[str, float], path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["channel_colours"] = {**data.get("channel_colours", {}), **colours}
    _save(path, data)


def identity(path: Path | None = None) -> Identity:
    saved = _load(path or paths.config_file())
    return Identity(me=tuple(saved.get("my_names", [])), crew=tuple(saved.get("crew", [])))


def save_identity(me: list[str], crew: list[str], path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["my_names"], data["crew"] = me, crew
    _save(path, data)


def autostart(path: Path | None = None) -> bool | None:
    """The user's "Start with Windows" choice; None until it has been made once (#45)."""
    return _load(path or paths.config_file()).get("autostart")


def save_autostart(on: bool, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["autostart"] = on
    _save(path, data)


def setup_state(path: Path | None = None) -> str | None:
    """First-start setup (#76): 'done', 'skipped', 'skipped-seen' (reminded once), or None.

    Installs from before the wizard count as done once a box was drawn or a name entered.
    """
    data = _load(path or paths.config_file())
    if "setup" in data:
        return data["setup"]
    if data.get("chat_boxes") or data.get("chat_regions") or data.get("my_names"):
        return "done"
    return None


def save_setup_state(state: str, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["setup"] = state
    _save(path, data)


def line_pictures(path: Path | None = None) -> bool:
    """Keep the picture of every chat line (#120); on unless switched off."""
    return _load(path or paths.config_file()).get("line_pictures", True)


def save_line_pictures(on: bool, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["line_pictures"] = on
    _save(path, data)


def debug_samples(path: Path | None = None) -> bool:
    """Collect debug samples (#63): on by default while YapTracker is a v0.x pre-release."""
    return _load(path or paths.config_file()).get("debug_samples", __version__.startswith("0."))


def save_debug_samples(on: bool, path: Path | None = None) -> None:
    path = path or paths.config_file()
    data = _load(path)
    data["debug_samples"] = on
    _save(path, data)


def change_detector(path: Path | None = None) -> ChangeDetector:
    """Skip-unchanged-frames thresholds (#17); defaults unless config.json says otherwise.

    "change_detection": {"new_share": 0.03, "min_pixels": 40}
    """
    return ChangeDetector(**_load(path or paths.config_file()).get("change_detection", {}))
