"""Yap snaps (#64): a funny chat moment as a pretty PNG to share.

Drawn with Pillow and the bundled fonts, so a snap looks the same on every PC (and is tested on
Linux). Names are hidden by default: other players become "Player 1", "Player 2"... in the
order they first speak, in their lines and wherever their name shows up in the text.
"""

import re
import time
from dataclasses import asdict, dataclass, fields, replace
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from yaptracker.glyphs import GLYPH

MAX_LINES = 20
SCALE = 2  # the PNG is drawn at twice the size, so it stays crisp on phones
WIDTH = 720
_FONTS = Path(__file__).parent / "ui" / "static" / "fonts"
_CHANNELS = ("team", "match", "group", "system")
_BRACKETED = re.compile(r"\[([^\]]+)\]")


@dataclass(frozen=True)
class SnapLine:
    channel: str  # team / match / group / system / chat
    who: str  # as shown: "NoodleBonk", "Player 2", "Me"; "" for system lines
    text: str
    time: str = ""  # in the match, "4:05"


@dataclass(frozen=True)
class Style:
    """How a snap looks (#65). Remembered in config.json, so the next snap looks the same."""

    background: str = "#0d1016"
    card: str = "#1a1f29"
    text: str = "#f2f4f8"
    accent: str = "#ff9c2a"
    team: str = "#5cc3ff"
    match: str = "#ffae4d"
    group: str = "#7ce38b"
    system: str = "#8a93a6"
    font: str = "nunito"  # nunito / barlow: the bundled fonts, nothing else
    rounded: bool = True
    timestamps: bool = False
    channel_labels: bool = True
    footer: bool = True
    wordmark: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Style":
        known = {f.name: type(getattr(cls(), f.name)) for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known and type(v) is known[k]})


_LOOKS = ("background", "card", "text", "accent", "team", "match", "group", "system")
PRESETS = {
    "night": ("YapTracker night", Style()),
    "light": ("Daylight", Style("#e9edf3", "#ffffff", "#1d2330", "#f08a00", "#1f7fd1", "#d9730d",
                                "#2f9e44", "#6b7385")),
    "pastel": ("Pastel", Style("#fbe4ef", "#fff7fb", "#4a3b52", "#ff6f9f", "#5b8def", "#f08c3c",
                               "#3fae7a", "#9a8aa6")),
    "contrast": ("High contrast", Style("#000000", "#000000", "#ffffff", "#ffd400", "#00e5ff",
                                        "#ffae00", "#5dff6b", "#d0d0d0")),
}  # fmt: skip


def preset_of(style: Style) -> str | None:
    """Which preset these colours are, or None for custom colours."""
    for key, (_, preset) in PRESETS.items():
        if all(getattr(style, c) == getattr(preset, c) for c in _LOOKS):
            return key
    return None


def with_preset(style: Style, key: str) -> Style:
    """The preset's colours; the font and the switches stay as they were."""
    return replace(style, **{c: getattr(PRESETS[key][1], c) for c in _LOOKS})


def _mix(a: str, b: str, t: float) -> str:
    """Colour a, moved t of the way to b: soft text, faint footer and borders from 4 colours."""
    pa, pb = (int(a[i : i + 2], 16) for i in (1, 3, 5)), (int(b[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb, strict=True))


def snap_lines(
    messages: list, hide_names: bool = True, keep_crew: bool = False, started_at: float = 0.0
) -> list[SnapLine]:
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
        seconds = max(0, int(getattr(m, "ts", 0.0) - started_at)) if started_at else 0
        rows.append((channel, who, m.text, f"{seconds // 60}:{seconds % 60:02d}"))
    lines = []
    for channel, who, text, when in rows:
        for name in sorted(fake, key=len, reverse=True):  # "gg NoodleBonk" too
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", fake[name], text, flags=re.I)
        lines.append(SnapLine(channel, who, text, when))
    return lines


@cache
def _font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_FONTS / name), size * SCALE)
    if weight is not None:
        font.set_variation_by_axes([weight])  # Nunito Sans is one variable font
    return font


def _face(family: str, size: int, weight: int, ext: bool = False) -> ImageFont.FreeTypeFont:
    subset = "latin-ext" if ext else "latin"
    if family == "barlow":  # static files: 700 for text, 800 for names
        return _font(f"barlow-condensed-{800 if weight >= 800 else 700}-normal-{subset}.woff2",
                     size + 2)  # fmt: skip
    return _font(f"nunito-sans-{subset}.woff2", size, weight)


def _is_ext(ch: str) -> bool:
    """In the latin-ext font file (Ł, ő, ș...), which has no basic letters: Google Fonts subsets."""
    return 0x100 <= ord(ch) <= 0x24F or 0x1E00 <= ord(ch) <= 0x1EFF


def _runs(text: str, size: int, weight: int, family: str = "nunito") -> list[tuple]:
    """The text in pieces, each with the font file that has its letters."""
    runs: list[tuple[str, bool]] = []
    for ch in text:
        if runs and runs[-1][1] == _is_ext(ch):
            runs[-1] = (runs[-1][0] + ch, runs[-1][1])
        else:
            runs.append((ch, _is_ext(ch)))
    return [(piece, _face(family, size, weight, ext)) for piece, ext in runs]


def _length(runs: list[tuple]) -> int:
    return int(sum(font.getlength(piece) for piece, font in runs))


def _tokens(text: str) -> list[str]:
    """Words with their trailing space; an emoji/icon chip (#128) is a token of its own."""
    spaced = text.replace(GLYPH, f" {GLYPH} ")
    return [word + " " for word in spaced.split()]


def _layout(lines: list[SnapLine], width: int, style: Style) -> tuple[list[tuple], int]:
    """Draw operations (kind, x, y, text, colour, font) for the lines, and their height."""
    s = SCALE
    line_h, gap = 26 * s, 8 * s
    time_w = 44 * s if style.timestamps else 0
    start = time_w + (64 * s if style.channel_labels else 0)
    soft, faint = _mix(style.text, style.card, 0.25), _mix(style.text, style.card, 0.55)
    ops, y = [], 0
    for line in lines:
        colour = getattr(style, line.channel) if line.channel in _CHANNELS else soft
        if style.timestamps:
            ops.append(("text", 0, y + 3 * s, line.time, faint, _face("nunito", 13, 600)))
        if style.channel_labels:
            ops.append(("text", time_w, y + 4 * s, line.channel.upper(), colour,
                        _face("nunito", 12, 800)))  # fmt: skip
        x = start
        pieces = [(f"{line.who}: ", colour, 800)] if line.who else []
        text_colour = soft if line.channel == "system" else style.text
        pieces += [(token, text_colour, 400) for token in _tokens(line.text)]
        for token, token_colour, weight in pieces:
            runs = [] if token.strip() == GLYPH else _runs(token, 17, weight, style.font)
            size = 18 * s if not runs else _length(runs)
            if x + size > width and x > start:
                x, y = start, y + line_h  # wrapped lines start under the name, like Live
            if not runs:
                ops.append(("glyph", x, y, "", faint, None))
            for piece, font in runs:
                ops.append(("text", x, y, piece, token_colour, font))
                x += int(font.getlength(piece))
            x += size if not runs else 0
        y += line_h + gap
    return ops, max(0, y - gap)


def render(
    lines: list[SnapLine], footer: str | None = None, style: Style | None = None
) -> Image.Image:
    """The snap: the lines on a card, the footer (match and date) and the wordmark, if wanted."""
    style, s = style or Style(), SCALE
    margin, pad = 24 * s, 24 * s
    inner = WIDTH * s - 2 * margin - 2 * pad
    ops, height = _layout(lines, inner, style)
    footer = footer if style.footer else None
    foot_h = 34 * s if footer or style.wordmark else 0
    card_h = pad + height + (18 * s + foot_h + pad // 2 if foot_h else pad)
    image = Image.new("RGB", (WIDTH * s, card_h + 2 * margin), style.background)
    draw = ImageDraw.Draw(image)
    border = _mix(style.card, style.text, 0.1)
    draw.rounded_rectangle((margin, margin, WIDTH * s - margin, margin + card_h),
                           radius=18 * s if style.rounded else 0, fill=style.card,
                           outline=border, width=s)  # fmt: skip
    left, top = margin + pad, margin + pad
    for kind, x, y, text, colour, font in ops:
        if kind == "glyph":  # a drawn diamond: the line had an emoji or icon OCR couldn't spell
            cx, cy, r = left + x + 7 * s, top + y + 13 * s, 6 * s
            draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                         outline=colour, width=2 * s)  # fmt: skip
        else:
            draw.text((left + x, top + y), text, fill=colour, font=font)
    if foot_h:
        base = margin + card_h - pad // 2 - foot_h
        draw.line((left, base, WIDTH * s - margin - pad, base), fill=border, width=s)
        x = left
        for piece, font in _runs(footer or "", 13, 600, style.font):
            draw.text((x, base + 10 * s), piece, fill=_mix(style.text, style.card, 0.55), font=font)
            x += font.getlength(piece)
        if style.wordmark:
            mark, word = _font("barlow-condensed-800-italic-latin.woff2", 20), "YAPTRACKER"
            draw.text((WIDTH * s - margin - pad - mark.getlength(word), base + 6 * s), word,
                      fill=style.accent, font=mark)  # fmt: skip
    return image


def save(image: Image.Image, folder: Path, now: float | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(now))
    path = folder / f"yapsnap-{stamp}.png"
    image.save(path, optimize=True)
    return path
