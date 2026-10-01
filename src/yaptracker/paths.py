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


def export_dir() -> Path:
    """Exports go where people look for their files: Documents\\YapTracker (#31, #69)."""
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL: the real Documents folder, also when OneDrive moved it
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # type: ignore[attr-defined]
        if buf.value:
            return Path(buf.value) / "YapTracker"
    return Path.home() / "Documents" / "YapTracker"
