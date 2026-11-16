"""Result unknown in up to half the matches (#555): the pale gold VICTORY! letters didn't count
as colour, so on a calm scene the banner was never read. Replay of Marv's 15 end samples,
2026-11-16 (crops at 1/8 size, names unreadable), each checked by eye."""

import json
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest

from yaptracker.signals import EndScreen, banner_outcome, has_colour

FIXTURES = Path(__file__).parent / "fixtures" / "signals"
SAMPLES = json.loads((FIXTURES / "end-2026-11-16.json").read_text(encoding="utf-8"))["samples"]
SHOWN = sorted(t for t, s in SAMPLES.items() if s["outcome"])


def crop(sample: str) -> np.ndarray:
    return cv2.imread(str(FIXTURES / "end-2026-11-16" / f"{sample}.png"))


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_every_result_a_human_can_see_is_read(sample):
    expected = SAMPLES[sample]
    if expected["outcome"]:
        assert has_colour(crop(sample))
    assert banner_outcome(expected["banner_read"]) == expected["outcome"]


def calm(image: np.ndarray, hues: tuple[int, int]) -> np.ndarray:
    """The same banner over a calm grey scene: only its bright letters (of these hues) stay."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    letters = (hsv[:, :, 2] >= 200) & (hsv[:, :, 0] >= hues[0]) & (hsv[:, :, 0] <= hues[1])
    out = np.full_like(image, 90)
    out[letters] = image[letters]
    return out


@pytest.mark.parametrize("sample", [t for t in SHOWN if SAMPLES[t]["outcome"] == "victory"])
def test_victory_counts_on_a_calm_scene_too(sample):
    gold = calm(crop(sample), (15, 45))
    hsv = cv2.cvtColor(gold, cv2.COLOR_BGR2HSV)
    saturated = float(((hsv[:, :, 1] > 120) & (hsv[:, :, 2] > 170)).mean())
    assert saturated < 0.08  # the old check alone: never read
    assert has_colour(gold)


@pytest.mark.parametrize("sample", [t for t in SHOWN if SAMPLES[t]["outcome"] == "defeat"])
def test_defeat_counts_on_a_calm_scene(sample):
    assert has_colour(calm(crop(sample), (130, 170)))  # the enemy colour: magenta here


def test_an_end_without_a_result_says_why(caplog):
    caplog.set_level(logging.INFO, "yaptracker.signals")
    clock, ends = [0.0], []
    reads = {"end_title": "PLAY OF THE GAME SIGMA"}
    screen = EndScreen(lambda image: reads.get(image.shape[0] == 75 and "end_title", "XQ"),
                       ends.append, lambda: clock[0])  # fmt: skip
    grey = np.full((250, 820, 3), 90, np.uint8)
    for _ in range(5):  # five looks at a calm, empty centre
        screen.update({"end_banner": grey})
        clock[0] += 1
    title = np.zeros((75, 900, 3), np.uint8)
    cv2.putText(
        title, "PLAY OF THE GAME", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4
    )
    screen.update({"end_banner": grey, "end_title": title})
    assert ends == [None]
    assert (
        "end screen: match over (PLAY OF THE GAME), no result read: 6 look(s) at the banner "
        "in the 30 s before, 0 coloured enough to read, none read as a result"
    ) in caplog.text
