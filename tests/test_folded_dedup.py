"""A better reading with umlauts replaces the first one instead of becoming a second line
(#293): dedup compares folded text (umlauts, ß/B, ◇, punctuation), stores the best reading."""

from yaptracker.capture.source import Region
from yaptracker.dedup import Dedup, match_key
from yaptracker.ocr.engine import OcrLine
from yaptracker.parser import parse


def read(*texts):
    return parse([OcrLine(t, 0.97, Region(64, 100 + 40 * n, 400, 24)) for n, t in enumerate(texts)])


def test_the_umlaut_reading_replaces_the_plain_one():
    """Marv's pair, 3 s apart (names replaced): 'mup mop map BBB >:3', then the re-read with
    umlauts 'müp möp map Bßß .3 ◇'."""
    dedup = Dedup()
    (yap,), _ = dedup.update(219.0, read("[Pickle]: mup mop map BBB >:3"))
    dedup.update(220.0, read("[Pickle]: mup mop map BBB >:3"))  # the plain one, read twice
    new, improved = dedup.update(222.0, read("[Pickle]: müp möp map Bßß .3 ◇"))
    assert new == [] and improved == [yap]
    assert yap.best.text == "müp möp map Bßß .3 ◇"


def test_folding_is_for_matching_only():
    (plain,), (dotted,) = read("[Pickle]: Grube :3"), read("[Pickle]: Grüße .3 ◇")
    assert match_key(plain) == match_key(dotted)
    assert dotted.text == "Grüße .3 ◇"  # what's stored keeps every letter and mark


def test_the_same_word_sent_again_behaves_like_any_repeat():
    """'schon' and then 'schön' sent on purpose behave exactly like 'schon' sent twice: folded,
    they're one key, so position and time decide as for any repeat (#293). (How dedup treats
    a quick repeat after another line is #296.)"""

    def after(earlier: list[str], now: list[str], text: str) -> list[str]:
        dedup = Dedup()
        dedup.update(100.0, read(*earlier))
        new, _ = dedup.update(103.0, read(*now, f"[Bo]: {text}"))
        return [y.best.text.replace("ö", "o") for y in new]

    for earlier, now in ((["[Ana]: hi", "[Bo]: schon"], ["[Ana]: hi", "[Bo]: schon"]),
                         (["[Bo]: schon"], ["[Bo]: schon", "[Ana]: ok"])):  # fmt: skip
        assert after(earlier, now, "schön") == after(earlier, now, "schon")
