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
