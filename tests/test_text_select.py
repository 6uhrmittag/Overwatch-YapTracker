"""Chat text can be selected and copied (#221): the native window allows it, a copy over several
lines is one "Name: message" per line (static/copy.js, run in node)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from yaptracker.app import native_window_args

COPY = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "copy.js"
CSS = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "theme.css"


def test_the_native_window_lets_text_be_selected():
    assert native_window_args(background=False)["text_select"] is True


def copy_text(lines: list[dict]) -> str:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    script = f"""
        const {{ ytCopyText }} = require({json.dumps(str(COPY))});
        process.stdout.write(ytCopyText({json.dumps(lines)}));
    """
    return subprocess.run(["node", "-e", script], capture_output=True, text=True,
                          check=True).stdout  # fmt: skip


def test_lines_copy_as_name_and_message():
    assert copy_text([
        {"name": "NoodleBonkl:", "text": " WAHoooo "},
        {"name": "you:", "text": "gg ◇"},
        {"name": "", "text": "Pickle started playing Overwatch."},  # system: the name is in it
        {"name": None, "text": ""},
    ]) == "NoodleBonkl: WAHoooo\nyou: gg ◇\nPickle started playing Overwatch."  # fmt: skip


def test_buttons_stickers_nav_and_chips_stay_unselectable():
    css = CSS.read_text(encoding="utf-8")
    rule = css[css.index("/* Text can be selected") :].split("}", 1)[0]
    for selector in ("button", ".yt-rail", ".yt-sticker", ".yt-quick", ".yt-keycap", ".yt-chip",
                     ".yt-line-time", ".yt-line-ch"):  # fmt: skip
        assert selector in rule
    assert "user-select: none" in rule
