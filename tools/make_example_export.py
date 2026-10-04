"""The example export in examples/export/ (#160): a made-up evening, exported like the app does.

    python tools/make_example_export.py

So people can see the format (docs/export-format.md) without having YapTracker or real chat.
Every name in here is invented. Times are fixed and in Europe/Berlin, so running it again
gives the same files; tests/test_example_export.py checks that.
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "export"
sys.path.insert(0, str(ROOT / "src"))

from yaptracker import export  # noqa: E402
from yaptracker.store.repo import Store  # noqa: E402


def berlin(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> float:
    return time.mktime((year, month, day, hour, minute, second, 0, 0, -1))


def evening(store: Store) -> None:
    session = store.start_session(berlin(2026, 10, 1, 20, 3, 0))
    noodle = store.add_player("NoodleBonk", berlin(2026, 9, 29, 20, 40, 0))
    store.add_alias(noodle, "NoodIeBonk")
    store.set_verdict(noodle, "friend")
    store.set_notes(noodle, "Hype Lúcio, says wahoo after every boop.\nGreet with a wahoo.")
    gremlin = store.add_player("gremlin.exe", berlin(2026, 10, 1, 20, 21, 0))
    store.set_verdict(gremlin, "avoid")
    crew = store.add_player("MoonPebble", berlin(2026, 9, 28, 19, 0, 0))

    first = store.start_match(session, berlin(2026, 10, 1, 20, 5, 0), "heroselect",
                              "UNRANKED", "ESPERANÇA")  # fmt: skip
    for minute, second, channel, who, pid, role, hero, text in [
        (6, 10, "match", "NoodleBonk", noodle, None, None, "gl hf wahoo"),
        (6, 31, "team", "tortillaTank", None, "me", None, "i go lucio"),
        (7, 2, "team", "MoonPebble", crew, "crew", "Kiriko", "Group up!"),
        (9, 45, "match", "NoodleBonk", noodle, None, None, "that rein was cracked ◇"),
        (12, 3, "team", "MoonPebble", crew, "crew", None, "kiri, I got you"),
    ]:
        store.add_message(ts=berlin(2026, 10, 1, 20, minute, second), channel=channel,
                          text=text, speaker_raw=who, player_id=pid, role=role, hero=hero,
                          match_id=first, ocr_confidence=0.98,
                          has_glyphs="◇" in text)  # fmt: skip
    store.end_match(first, berlin(2026, 10, 1, 20, 16, 0), "victory")
    store.set_loved(first, berlin(2026, 10, 1, 20, 17, 0))  # hearted after the win (#282)
    store.add_message(ts=berlin(2026, 10, 1, 20, 16, 40), channel="system",
                      text="Endorsement Received!", match_id=first)  # fmt: skip

    second = store.start_match(session, berlin(2026, 10, 1, 20, 20, 0), "heroselect",
                               "UNRANKED", "ROUTE 66")  # fmt: skip
    store.add_message(ts=berlin(2026, 10, 1, 20, 21, 5), channel="system",
                      text="[gremlin.exe] joined the game.", speaker_raw="gremlin.exe",
                      match_id=second)  # fmt: skip
    spicy = store.add_message(ts=berlin(2026, 10, 1, 20, 23, 12), channel="match",
                              text="ez", speaker_raw="gremlin.exe", player_id=gremlin,
                              match_id=second, ocr_confidence=0.95,
                              flagged="overwatch")  # fmt: skip
    gap = store.open_gap(berlin(2026, 10, 1, 20, 25, 0), "no_frames")
    store.close_gap(gap, berlin(2026, 10, 1, 20, 26, 30))
    store.add_message(ts=berlin(2026, 10, 1, 20, 29, 50), channel="match",
                      text="gg wp, wahoo", speaker_raw="NoodleBonk", player_id=noodle,
                      match_id=second, ocr_confidence=0.99)  # fmt: skip
    store.end_match(second, berlin(2026, 10, 1, 20, 31, 0), "defeat")
    store.end_session(session, berlin(2026, 10, 1, 20, 35, 0))
    seen = {noodle: (20, 29, 50), gremlin: (20, 23, 12), crew: (20, 12, 3)}
    for pid, (hour, minute, second) in seen.items():
        store.player_seen(pid, berlin(2026, 10, 1, hour, minute, second))
    assert spicy


def make(out: Path = OUT) -> Path:
    zone, version = os.environ.get("TZ"), export.__version__
    os.environ["TZ"] = "Europe/Berlin"
    time.tzset()
    export.__version__ = "0.4.example"  # the same file whatever version makes it
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store.open(Path(tmp) / "yaptracker.db", Path(tmp) / "backups")
            try:
                evening(store)
                shutil.rmtree(out, ignore_errors=True)
                now = berlin(2026, 10, 1, 22, 0)
                return export.export_all(store, out, now, markdown=True)
            finally:
                store.close()
    finally:  # back to how it was: tests call this too
        export.__version__ = version
        if zone is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = zone
        time.tzset()


if __name__ == "__main__":
    print(make())
