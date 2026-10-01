"""Yap snaps (#64): a funny chat moment as a pretty PNG to share.

Drawn with Pillow and the bundled fonts, so a snap looks the same on every PC (and is tested on
Linux). Names are hidden by default: other players become "Player 1", "Player 2"... in the
order they first speak, in their lines and wherever their name shows up in the text.
"""

import re
import time
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from yaptracker.glyphs import GLYPH

MAX_LINES = 20
SCALE = 2  # the PNG is drawn at twice the size, so it stays crisp on phones
WIDTH = 720
_FONTS = Path(__file__).parent / "ui" / "static" / "fonts"
_NIGHT, _PANEL, _BORDER = "#0d1016", "#1a1f29", "#252b38"
_TEXT, _SOFT, _FAINT, _ACCENT = "#f2f4f8", "#c3cad8", "#6f788c", "#ff9c2a"
_CHANNELS = {"team": "#5cc3ff", "match": "#ffae4d", "group": "#7ce38b", "system": "#8a93a6"}
_BRACKETED = re.compile(r"\[([^\]]+)\]")


@dataclass(frozen=True)
class SnapLine:
    channel: str  # team / match / group / system / chat
    who: str  # as shown: "NoodleBonk", "Player 2", "Me"; "" for system lines
    text: str


def snap_lines(messages: list, hide_names: bool = True, keep_crew: bool = False) -> list[SnapLine]:
    """Chat messages as they appear on the snap. `keep_crew`: me and my crew keep their names."""
    fake: dict[str, str] = {}  # hidden name (casefolded) -> what the snap shows
    numbered = 0

    def alias(name: str, role: str | None = None) -> str:
        nonlocal numbered
        if not hide_names or (keep_crew and role in ("me", "crew")):
            return name
        if name.casefold() not in fake:
            if role == "me":
                fake[name.casefold()] = "Me"
            else:
                numbered += 1
                fake[name.casefold()] = f"Player {numbered}"
        return fake[name.casefold()]

    rows = []
    for m in messages:  # in order, so Player 1 is whoever shows up first
        channel = m.channel if m.channel in _CHANNELS else "chat"
        if channel == "system":  # "[gremlin.exe] started playing Overwatch."
            for name in _BRACKETED.findall(m.text):
                alias(name)
        who = "" if channel == "system" else alias(m.speaker_raw or "?", m.role)
        rows.append((channel, who, m.text))
    lines = []
    for channel, who, text in rows:
        for name in sorted(fake, key=len, reverse=True):  # "gg NoodleBonk" too
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", fake[name], text, flags=re.I)
        lines.append(SnapLine(channel, who, text))
    return lines


@cache
def _font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_FONTS / name), size * SCALE)
    if weight is not None:
        font.set_variation_by_axes([weight])  # Nunito Sans is one variable font
    return font


def _nunito(size: int, weight: int, ext: bool = False) -> ImageFont.FreeTypeFont:
    return _font(f"nunito-sans-latin{'-ext' if ext else ''}.woff2", size, weight)


def _is_ext(ch: str) -> bool:
    """In the latin-ext font file (Ł, ő, ș...), which has no basic letters: Google Fonts subsets."""
    return 0x100 <= ord(ch) <= 0x24F or 0x1E00 <= ord(ch) <= 0x1EFF


def _runs(text: str, size: int, weight: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """The text in pieces, each with the font file that has its letters."""
    runs: list[tuple[str, bool]] = []
    for ch in text:
        if runs and runs[-1][1] == _is_ext(ch):
            runs[-1] = (runs[-1][0] + ch, runs[-1][1])
        else:
            runs.append((ch, _is_ext(ch)))
    return [(piece, _nunito(size, weight, ext)) for piece, ext in runs]


def _length(runs: list[tuple[str, ImageFont.FreeTypeFont]]) -> int:
    return int(sum(font.getlength(piece) for piece, font in runs))


def _tokens(text: str) -> list[str]:
    """Words with their trailing space; an emoji/icon chip (#128) is a token of its own."""
    spaced = text.replace(GLYPH, f" {GLYPH} ")
    return [word + " " for word in spaced.split()]


def _layout(lines: list[SnapLine], width: int) -> tuple[list[tuple], int]:
    """Draw operations (kind, x, y, text, colour, font) for the lines, and their height."""
    s = SCALE
    line_h, chip_w, gap = 26 * s, 64 * s, 8 * s
    ops, y = [], 0
    for line in lines:
        colour = _CHANNELS.get(line.channel, _SOFT)
        ops.append(("text", 0, y + 4 * s, line.channel.upper(), colour, _nunito(12, 800)))
        x = chip_w
        pieces = [(f"{line.who}: ", colour, 800)] if line.who else []
        text_colour = _SOFT if line.channel == "system" else _TEXT
        pieces += [(token, text_colour, 400) for token in _tokens(line.text)]
        for token, token_colour, weight in pieces:
            runs = [] if token.strip() == GLYPH else _runs(token, 17, weight)
            size = 18 * s if not runs else _length(runs)
            if x + size > width and x > chip_w:
                x, y = chip_w, y + line_h  # wrapped lines start under the name, like Live
            if not runs:
                ops.append(("glyph", x, y, "", _FAINT, None))
            for piece, font in runs:
                ops.append(("text", x, y, piece, token_colour, font))
                x += int(font.getlength(piece))
            x += size if not runs else 0
        y += line_h + gap
    return ops, max(0, y - gap)


def render(lines: list[SnapLine], footer: str | None = None) -> Image.Image:
    """The snap: the lines on a YapTracker card, an optional footer, the wordmark."""
    s = SCALE
    margin, pad = 24 * s, 24 * s
    inner = WIDTH * s - 2 * margin - 2 * pad
    ops, height = _layout(lines, inner)
    foot_h = 34 * s
    card_h = pad + height + 18 * s + foot_h + pad // 2
    image = Image.new("RGB", (WIDTH * s, card_h + 2 * margin), _NIGHT)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((margin, margin, WIDTH * s - margin, margin + card_h), radius=18 * s,
                           fill=_PANEL, outline=_BORDER, width=s)  # fmt: skip
    left, top = margin + pad, margin + pad
    for kind, x, y, text, colour, font in ops:
        if (
            kind == "glyph"
        ):  # \u25c7 shown as a diamond: the line had an emoji or icon OCR couldn't spell
            cx, cy, r = left + x + 7 * s, top + y + 13 * s, 6 * s
            draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                         outline=colour, width=2 * s)  # fmt: skip
        else:
            draw.text((left + x, top + y), text, fill=colour, font=font)
    base = margin + card_h - pad // 2 - foot_h
    draw.line((left, base, WIDTH * s - margin - pad, base), fill=_BORDER, width=s)
    if footer:
        x = left
        for piece, font in _runs(footer, 13, 600):
            draw.text((x, base + 10 * s), piece, fill=_FAINT, font=font)
            x += font.getlength(piece)
    mark = _font("barlow-condensed-800-italic-latin.woff2", 20)
    word = "YAPTRACKER"
    draw.text((WIDTH * s - margin - pad - mark.getlength(word), base + 6 * s), word,
              fill=_ACCENT, font=mark)  # fmt: skip
    return image


def save(image: Image.Image, folder: Path, now: float | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(now))
    path = folder / f"yapsnap-{stamp}.png"
    image.save(path, optimize=True)
    return path
