"""Skip unchanged frames (#17), replayed from synthetic frames like the real chat.

Real recordings can't be committed, so the hard parts are rebuilt: a moving scene behind the
chat, animated letter-sized sparkles, lines fading out, and one new line.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from yaptracker.capture.changes import ChangeDetector, text_mask
from yaptracker.capture.replay import ReplayFrameSource

W, H = 615, 395
ORANGE = (255, 174, 77)
LINES = ["[NoodleBonk]: WAHOOOO", "[tortillaTank]: not the wahoo guy again", "[Bapricot]: gg"]


def frame(t: int, lines: int, fade: float = 1.0, sparkles: bool = False) -> Image.Image:
    rng = np.random.default_rng(t)
    y, x = np.mgrid[0:H, 0:W]
    scene = np.stack(
        [80 + 60 * np.sin((x + 15 * t) / 90), 70 + 50 * np.cos((y + 9 * t) / 70), 60 + 0 * x], -1
    )
    img = Image.fromarray(np.clip(scene, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    if sparkles:  # animated, letter-sized bright bits that move every frame
        for _ in range(40):
            cx, cy = rng.integers(20, W - 20), rng.integers(20, H - 20)
            draw.ellipse((cx - 4, cy - 6, cx + 4, cy + 6), fill=ORANGE, outline=(0, 0, 0), width=2)
    font = ImageFont.load_default(size=22)
    colour = tuple(int(c * fade) for c in ORANGE)
    for i, text in enumerate(LINES[:lines]):
        draw.text((20, H - 40 * (lines - i)), text, fill=colour, font=font, stroke_width=2,
                  stroke_fill=(0, 0, 0))  # fmt: skip
    return img


def replay(tmp_path, images):
    for i, image in enumerate(images):
        image.save(tmp_path / f"{i * 250:07d}.png")
    detector = ChangeDetector()
    changed = [
        i for i, f in enumerate(ReplayFrameSource(tmp_path).frames()) if detector.update(f.image)
    ]
    return changed, detector


def test_text_mask_sees_chat_text_but_not_the_scene():
    assert text_mask(np.asarray(frame(0, 0))[:, :, ::-1].copy()).sum() == 0
    assert text_mask(np.asarray(frame(0, 2))[:, :, ::-1].copy()).sum() > 500


def test_moving_scene_and_sparkles_are_skipped_new_line_is_not(tmp_path):
    images = [frame(t, 2) for t in range(6)]  # two lines, the scene moves behind them
    images += [frame(t, 2, sparkles=True) for t in range(6, 12)]  # animated effects
    images += [frame(t, 3) for t in range(12, 16)]  # a new message arrives at frame 12
    changed, detector = replay(tmp_path, images)
    # Frame 1 confirms the first text (new text must still be there one frame later),
    # frame 13 confirms the new message. Everything else is skipped.
    assert changed == [1, 13]
    assert detector.skipped_share > 0.8


def test_fading_lines_are_not_new_text(tmp_path):
    fades = (0.9, 0.8, 0.7, 0.6, 0.5)  # end of match: the lines slowly disappear
    images = [frame(t, 3) for t in range(3)]
    images += [frame(3 + i, 3, fade=f) for i, f in enumerate(fades)]
    changed, _ = replay(tmp_path, images)
    assert changed == [1]


def test_thresholds_come_from_config(tmp_path):
    import json

    from yaptracker import config

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"change_detection": {"new_share": 0.1, "min_pixels": 99}}))
    detector = config.change_detector(path)
    assert (detector.new_share, detector.min_pixels) == (0.1, 99)
