"""Shared bits of the OCR POC (#608): where the private data lives and how readings compare.

Everything private (pictures, DB copy, labels, checkpoints) stays under fixtures/private/ocr of
the MAIN checkout (gitignored), also when a script runs from a worktree. Never committed.
"""

import re
import subprocess
import sys
from pathlib import Path

DATA = Path("/mnt/c/Users/marvi/AppData/Local/YapTracker/data")  # the installed app's data
_ICON = re.compile(r"\[icon:[a-z0-9-]+\]|◇")


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
        done = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq Overwatch.exe", "/NH"],
            capture_output=True, timeout=20,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return True  # can't tell: stay off the GPU
    out = done.stdout.decode("ascii", errors="replace")  # a German Windows answers in cp850
    if done.returncode != 0 or not out.strip():
        return True  # tasklist failed: can't tell either
    return "overwatch.exe" in out.lower()


GAME_EXIT = 3  # every heavy step ends with this when Overwatch is there; run.py goes on later


def no_game(done: str = "") -> None:
    """Stop here if Overwatch is running: nothing heavy next to the game (#608's rule)."""
    if game_running():
        print(f"Overwatch is running: stopped{done}")
        sys.exit(GAME_EXIT)


def plain(text: str | None) -> str:
    """A reading as it is compared: no icon marks (no engine can spell them), single spaces."""
    return " ".join(_ICON.sub(" ", text or "").split())


def errors(truth: str, got: str) -> tuple[int, int]:
    """(wrong characters, characters) of one field: Levenshtein distance against the truth."""
    from rapidfuzz.distance import Levenshtein  # not in the POC's own venv (vlm_reread.py)

    truth, got = plain(truth), plain(got)
    return Levenshtein.distance(truth, got), len(truth)
