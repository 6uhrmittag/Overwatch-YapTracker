"""Shared bits of the OCR POC (#608): where the private data lives and how readings compare.

Everything private (pictures, DB copy, labels, checkpoints) stays under fixtures/private/ocr of
the MAIN checkout (gitignored), also when a script runs from a worktree. Never committed.
"""

import re
import subprocess
from pathlib import Path

from rapidfuzz.distance import Levenshtein

DATA = Path("/mnt/c/Users/marvi/AppData/Local/YapTracker/data")  # the installed app's data
_ICON = re.compile(r"\[icon:[a-z-]+\]|◇")


def private() -> Path:
    """fixtures/private/ocr of the main checkout: a worktree shares it instead of losing it."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, check=True, cwd=Path(__file__).parent,
    ).stdout.strip()  # fmt: skip
    return Path(common).parent / "fixtures" / "private" / "ocr"


def game_running() -> bool:
    """Overwatch is open: no heavy step may start or go on (#608's rule)."""
    try:
        out = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq Overwatch.exe", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return True  # can't tell: stay off the GPU
    return "overwatch.exe" in out.lower()


def plain(text: str | None) -> str:
    """A reading as it is compared: no icon marks (no engine can spell them), single spaces."""
    return " ".join(_ICON.sub(" ", text or "").split())


def errors(truth: str, got: str) -> tuple[int, int]:
    """(wrong characters, characters) of one field: Levenshtein distance against the truth."""
    truth, got = plain(truth), plain(got)
    return Levenshtein.distance(truth, got), len(truth)
