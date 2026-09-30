"""Fake data for `--dev` review in a browser. Made-up names only - the repo is public."""

from PIL import Image, ImageDraw, ImageFont

from yaptracker.capture.source import default_chat_region

ENABLED = False  # set by `python -m yaptracker --dev`

_LINES = [
    ((255, 174, 77), "[NoodleBonk]: WAHOOOO"),
    ((255, 174, 77), "[tortillaTank]: not the wahoo guy again lmao"),
    ((124, 227, 139), "SirPeelsALot (Reinhardt): Group up!"),
    ((124, 227, 139), "[Bapricot]: drop the lamp on me pls"),
    ((255, 214, 90), "[gremlin.exe] started playing Overwatch."),
    ((255, 174, 77), "[NoodleBonk]: it is literally the first fight"),
]


def screenshot(width: int = 2560, height: int = 1440) -> Image.Image:
    """A stand-in for an Overwatch screenshot: sky gradient plus chat lines in the usual spot."""
    top, bottom = (43, 61, 85), (107, 90, 42)
    gradient = Image.linear_gradient("L").resize((width, height))
    channels = [
        gradient.point(lambda v, a=a, b=b: a + (b - a) * v // 255)
        for a, b in zip(top, bottom, strict=True)
    ]
    img = Image.merge("RGB", channels)
    draw = ImageDraw.Draw(img)
    region = default_chat_region(width, height)
    font = ImageFont.load_default(size=round(height / 52))
    y = region.y + region.height - len(_LINES) * font.size * 1.6
    for colour, text in _LINES:
        draw.text((region.x + 20, y), text, fill=colour, font=font, stroke_width=2, stroke_fill=0)
        y += font.size * 1.6
    return img
