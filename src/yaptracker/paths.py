"""Where YapTracker keeps its data. Updates replace the app folder, never this one."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "YapTracker" / "data"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "yaptracker"


def log_file() -> Path:
    return data_dir() / "logs" / "yaptracker.log"


def config_file() -> Path:
    return data_dir() / "config.json"


def db_file() -> Path:
    return data_dir() / "yaptracker.db"


def backup_dir() -> Path:
    return data_dir() / "backups"


def debug_dir() -> Path:
    return data_dir() / "debug"


def lines_dir() -> Path:
    return data_dir() / "lines"


def _known_folder(csidl: int, name: str) -> Path:
    """A Windows user folder (the real one, also when OneDrive moved it), or ~/<name>."""
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)  # type: ignore[attr-defined]
        if buf.value:
            return Path(buf.value)
    return Path.home() / name


def export_dir() -> Path:
    """Exports go where people look for their files: Documents\\YapTracker (#31, #69)."""
    return _known_folder(0x05, "Documents") / "YapTracker"  # CSIDL_PERSONAL


def pictures_dir() -> Path:
    """Yap snaps (#64): Pictures\\YapTracker."""
    return _known_folder(0x27, "Pictures") / "YapTracker"  # CSIDL_MYPICTURES
