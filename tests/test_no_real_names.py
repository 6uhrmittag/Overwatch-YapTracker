"""No real player name in the repo, ever (CLAUDE.md: the repo is public).

Collects every name read with confidence from the private samples (fixtures/private and the
app's own debug samples) and fails if one of them shows up in a tracked file. The private data
only exists on Marv's PC, so this runs there and skips in CI.
"""

import glob
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DEBUG = "/mnt/c/Users/*/AppData/Local/YapTracker/data/debug/*/*-chat/sample.json"
SURE = 0.95  # garbled readings of cut lines are not names anyone could find
WORDS = {"Match", "Team", "Group", "System", "Report", "Zero"}  # read as names, are words
WORDS |= {"Copy", "final"}  # players named like words: in our code they're the words (#369)
_NAME = re.compile(r"^\[([^\]\s]{4,})\]|^([^\s\[\]()]{4,})\s*\(")


def private_names() -> set[str]:
    names = set()
    for path in glob.glob(str(ROOT / "fixtures/private/ocr-seq/*.json")):
        for frame in json.loads(Path(path).read_text(encoding="utf-8"))["frames"]:
            for line in frame["ocr"]:
                if line["confidence"] >= SURE and (m := _NAME.match(line["text"])):
                    names.add(m[1] or m[2])
    for path in glob.glob(DEBUG):
        for frame in json.loads(Path(path).read_text(encoding="utf-8"))["frames"]:
            for line in frame["parsed"]:
                if line.get("speaker") and line["confidence"] >= SURE:
                    names.add(line["speaker"])
    return {n for n in names if len(n) >= 4 and n not in WORDS and re.search(r"[A-Za-z]", n)}


def test_no_name_from_the_private_samples_is_committed():
    names = private_names()
    if not names:
        pytest.skip("no private samples here (CI): nothing to compare against")
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()  # fmt: skip
    found = re.compile(r"(?<![\w#])(" + "|".join(map(re.escape, names)) + r")(?![\w#])")
    leaks = {}
    for name in files:
        if name.startswith("tools/github-setup/"):
            continue
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # pictures, models: no text
        if hits := set(found.findall(text)):
            leaks[name] = sorted(hits)
    assert leaks == {}, f"real player names in tracked files: {leaks}"
