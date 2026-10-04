"""Callouts as the wheel says them (#290), from #260's Live list (names replaced): fragments
are no lines, misreads are corrected, a garbled speaker on the same hero is the same line."""

import numpy as np
import pytest

from yaptracker.callouts import normalise
from yaptracker.capture.source import Region
from yaptracker.identity import Identity
from yaptracker.matches import MatchTracker
from yaptracker.ocr.engine import OcrLine
from yaptracker.pause import Pause
from yaptracker.reader import ChatReader
from yaptracker.store.repo import Store

BLACK = np.zeros((395, 615, 3), np.uint8)


@pytest.mark.parametrize(("read", "said"), [
    ("Eall back!", "Fall back!"), ("Hello", "Hello!"), ("I am so sorry.", "I'm so sorry."),
    ("Enemy llari!", "Enemy Illari!"), ("Enemy Siera", "Enemy Sierra!"),
    ("Enemy S Sombra at Low Health!", "Enemy Sombra at Low Health!"),
    ("My ultimate (EMP) iS ready!", "My ultimate (EMP) is ready!"),
    ("Fall back! I'm e di waiting to respawn! (12s)", "Fall back! I'm waiting to respawn! (12s)"),
    ("wants to attaek the", "wants to attack the objective!"), ("Hello! OBACK", "Hello!"),
    ("Something new!", "Something new!"),  # a callout we don't know yet: kept as read
])  # fmt: skip
def test_readings_become_the_wheels_phrase(read, said):
    assert normalise(read) == said


@pytest.mark.parametrize("fragment", ["My", "/ Enemy", "En", "wants to"])
def test_fragments_are_no_callout(fragment):
    assert normalise(fragment) is None


def line(text, y):
    return OcrLine(text, 0.97, Region(64, y, 400, 24))


def test_the_live_list_from_260(tmp_path):
    """#260's screenshot: 'Mochi: My', 'Mochi: / Enemy', 'you: Enemy Sierra!' then the same line
    read as 'MW: Enemy Siera', and 'you: wants to attack the objective!'."""
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        tracker = MatchTracker(store, Pause())
        tracker.capture_alive(1000.0)
        frames = [
            [line("Pickle (Sombra): Enemy Sierra!", 300)],
            [line("Pickle (Sombra): Enemy Sierra!", 260), line("Mochi (Zarya): My", 300)],
            [line("MW (Sombra): Enemy Siera", 220), line("Mochi (Zarya): / Enemy", 260),
             line("Pickle (Sombra) wants to attack the objective!", 300)],
        ]  # fmt: skip
        reads = iter(frames)
        reader = ChatReader(lambda _: next(reads), store, tracker,
                            identity=lambda: Identity(me=("Pickle",)))  # fmt: skip
        for t in range(len(frames)):
            reader.read_frame(1000.0 + 2 * t, BLACK.copy())
        stored = [(m.speaker_raw, m.text) for m in store.messages(tracker.match_id)]
        assert stored == [("Pickle", "Enemy Sierra!"),
                          ("Pickle", "wants to attack the objective!")]  # fmt: skip
    finally:
        store.close()
