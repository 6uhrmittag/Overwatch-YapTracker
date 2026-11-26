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


def test_one_misread_with_an_accent_doesnt_beat_the_many_right_readings():
    """#631, the chat-trained engine on a recorded match (names replaced): "glhf <3" read right
    on every clean frame and once, with an outline behind it, as "glhif <ß". The ß made that
    single reading win. An accented reading only wins as the usual one with its umlauts."""
    from yaptracker.dedup import Yap

    (right,), (wrong,) = read("[Pickle]: glhf <3"), read("[Pickle]: glhif <ß")
    yap = Yap(id=1, first_seen=100.0)
    for line in (right, right, wrong, right):
        yap.add(line)
    assert yap.best.text == "glhf <3"
    yap.add(wrong)  # read twice now, the right one three times
    assert yap.best.text == "glhf <3"


def test_the_umlaut_reading_still_wins_when_it_is_the_same_text():
    from yaptracker.dedup import Yap

    (plain,), (dotted,) = (
        read("[Pickle]: Schone GruBe an alle"),
        read("[Pickle]: Schöne Grüße an alle"),
    )
    yap = Yap(id=1, first_seen=100.0)
    for line in (plain, plain, plain, dotted):
        yap.add(line)
    assert yap.best.text == "Schöne Grüße an alle"
