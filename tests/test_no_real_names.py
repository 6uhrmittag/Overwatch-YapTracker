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
GAME_LISTS = ROOT / "src" / "yaptracker" / "data" / "game_lists.json"


def game_words() -> set[str]:
    """Every word of the game's own names (heroes, maps, map types, queues), lower case (#483):
    a player who calls themselves "Green" can't be told apart from "Workshop Green Screen", so
    those names aren't checked. The file's other text (source, URL) doesn't count."""
    lists = json.loads(GAME_LISTS.read_text(encoding="utf-8"))
    types = [t for value in lists["map_types"].values() for t in (value if isinstance(value, list)
                                                                  else [value])]  # fmt: skip
    entries = [*lists["heroes"], *lists["maps"], *lists["queues"], *types]
    return {w.casefold() for entry in entries for w in re.findall(r"[^\W\d_]+", entry)}


def checkable(names: set[str]) -> set[str]:
    """The names worth looking for: not our UI words, not the game's own words."""
    game = game_words()
    return {n for n in names if len(n) >= 4 and n not in WORDS and re.search(r"[A-Za-z]", n)
            and n.casefold() not in game}  # fmt: skip


def leaks_in(names: set[str], texts: dict[str, str]) -> dict[str, list[str]]:
    if not names:
        return {}  # an empty pattern would match everywhere
    found = re.compile(r"(?<![\w#])(" + "|".join(map(re.escape, names)) + r")(?![\w#])")
    return {
        path: sorted(hits) for path, text in texts.items() if (hits := set(found.findall(text)))
    }


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
    return checkable(names)


def test_no_name_from_the_private_samples_is_committed():
    names = private_names()
    if not names:
        pytest.skip("no private samples here (CI): nothing to compare against")
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()  # fmt: skip
    texts = {}
    for name in files:
        if name.startswith("tools/github-setup/"):
            continue
        try:
            texts[name] = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # pictures, models: no text
    leaks = leaks_in(names, texts)
    assert leaks == {}, f"real player names in tracked files: {leaks}"


def test_a_real_looking_name_is_still_caught_and_a_game_word_is_not():
    """#483: "Green" (a word of the game lists) stopped every local run; names stay strict."""
    names = checkable({"Garbleguy", "Green", "Match", "Source"})
    assert names == {"Garbleguy", "Source"}  # the file's metadata words stay checked
    texts = {"tests/fixtures/chat/x.json": '{"speaker": "Garbleguy"}', "game.json": "Green Day"}
    assert leaks_in(names, texts) == {"tests/fixtures/chat/x.json": ["Garbleguy"]}
    assert leaks_in(set(), texts) == {}
