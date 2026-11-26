"""#637 spike: how many lines a night would send to the AI, trigger by trigger.

    python tools/ocr_train/ai_triggers.py [--evenings 8]

From a copy of the app's DB (fixtures/private/ocr/db637) and the line pictures: per evening,
how many stored lines each trigger of #637 would have sent, and all triggers together. The
"readings disagree" trigger isn't in the DB (dedup keeps only the best reading): ai_spike.py
estimates it from a replay. Prints counts only.
"""

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
from inventory import WRAP_HEIGHT  # noqa: E402

from yaptracker.days import day_of  # noqa: E402
from yaptracker.glyphs import has_glyphs  # noqa: E402
from yaptracker.ocr.engine import looks_german  # noqa: E402

NEAR = 80  # fuzzy ratio: this close to a known name, but not it
SHORT = 3  # characters of text
_ACCENT = re.compile(r"[äöüßÄÖÜ]")


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--evenings", type=int, default=8)
    opts = args.parse_args()
    private = common.private()
    db = sqlite3.connect(private / "db637" / "yaptracker.db")
    names_at: list[tuple[float, str]] = sorted(
        [(first, name.lower()) for name, first in db.execute(
            "SELECT display_name, first_seen FROM players")]
        + [(first, alias.lower()) for alias, first in db.execute(
            "SELECT a.alias, p.first_seen FROM player_aliases a JOIN players p "
            "ON p.id = a.player_id")]
    )  # fmt: skip
    rows = db.execute(
        "SELECT id, ts, channel, speaker_raw, text, has_glyphs, edited_at FROM chat_messages "
        "WHERE deleted_at IS NULL ORDER BY ts"
    ).fetchall()
    days = sorted({day_of(r[1]) for r in rows})[-opts.evenings :]
    pictures = {int(p.stem): p for p in (private / "lines").rglob("*.webp") if p.stem.isdigit()}
    edited_speakers: set[str] = set()
    edited_tonight: set[tuple[str, str]] = set()  # the narrow variant: an edit this evening
    per: dict[str, Counter] = defaultdict(Counter)
    for message_id, ts, channel, speaker, text, glyphs, edited in rows:
        day = day_of(ts)
        speaker_l = (speaker or "").lower()
        hits = set()
        if day in days:
            system = channel == "system"
            if speaker_l:
                known = [n for first, n in names_at if first < ts and n != speaker_l]
                exact = any(n == speaker_l for first, n in names_at if first < ts)
                best = process.extractOne(speaker_l, known, scorer=fuzz.ratio) if known else None
                if not exact and best and best[1] >= NEAR:
                    hits.add("name near-miss")
            if glyphs or has_glyphs(text):
                hits.add("icon (◇)")
            if not system and (_ACCENT.search(text) or looks_german(text)):
                hits.add("umlauts / German")
            if not system and len(text.strip()) <= SHORT:
                hits.add("very short")
            path = pictures.get(message_id)
            if path is not None and Image.open(path).size[1] >= WRAP_HEIGHT:
                hits.add("wrapped")
            if speaker_l and speaker_l in edited_speakers:
                hits.add("speaker edited before")
            if speaker_l and (speaker_l, day) in edited_tonight:
                hits.add("edited tonight")
            per[day]["lines"] += 1
            per[day]["no picture"] += path is None
            for hit in hits:
                per[day][hit] += 1
            per[day]["any trigger"] += bool(hits)
            per[day]["any, narrow"] += bool(hits - {"speaker edited before"})
        if edited is not None and speaker_l:
            edited_speakers.add(speaker_l)
            edited_tonight.add((speaker_l, day))
    columns = ["lines", "name near-miss", "icon (◇)", "umlauts / German", "very short",
               "wrapped", "speaker edited before", "edited tonight", "any trigger",
               "any, narrow"]  # fmt: skip
    print("evening     " + "  ".join(f"{c[:14]:>14}" for c in columns))
    for day in days:
        print(f"{day}  " + "  ".join(f"{per[day][c]:>14}" for c in columns))
    total = Counter()
    for day in days:
        total.update(per[day])
    print("mean/evening" + "  ".join(f"{total[c] / len(days):>14.0f}" for c in columns))


if __name__ == "__main__":
    main()
