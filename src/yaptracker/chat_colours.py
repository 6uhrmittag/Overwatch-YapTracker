"""Chat colours (#401): the colour of each channel in Live, transcripts, search and yap snaps.

Overwatch's own defaults, so YapTracker looks like the chat box people know, and changeable in
Settings, because players pick their own chat colours in Overwatch. System lines stay grey by
default (Marv: Overwatch's yellow is too bright here); "Chat" is a line no channel was found for.
"""

import re

from yaptracker import config

DEFAULTS = {
    "team": "#00c1ff",
    "match": "#fd8d00",
    "group": "#7ce38b",
    "system": "#8a93a6",
    "chat": "#9aa3b5",
}
NAMES = {"team": "Team", "match": "Match", "group": "Group", "system": "System", "chat": "Chat"}
PANEL = "#1a1f29"  # the card the lines sit on
READABLE = 3.0  # WCAG contrast for bold text: below it, a colour is hard to read on the panel
_HEX = re.compile(r"^#[0-9a-f]{6}$")


def valid(colour: object) -> bool:
    return isinstance(colour, str) and bool(_HEX.match(colour.lower()))


def current() -> dict[str, str]:
    """Every channel's colour: the saved one, else the default."""
    saved = config.chat_colours()
    return {k: saved[k].lower() if valid(saved.get(k)) else v for k, v in DEFAULTS.items()}


def save(channel: str, colour: str) -> dict[str, str]:
    config.save_chat_colours({**current(), channel: colour.lower()})
    return current()


def reset() -> dict[str, str]:
    config.save_chat_colours({})
    return current()


def _luminance(colour: str) -> float:
    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(int(colour[i : i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str = PANEL) -> float:
    """WCAG contrast ratio, 1 (none) to 21 (black on white)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable(colour: str) -> bool:
    return contrast(colour) >= READABLE


def css(colours: dict[str, str]) -> str:
    """The colours as theme variables; `html:root` wins over theme.css whatever loads first."""
    return "html:root {" + "".join(f" --yt-{k}: {v};" for k, v in colours.items()) + " }"


def js(colours: dict[str, str]) -> str:
    """The same, for a page that's already open: no restart needed."""
    sets = "".join(f"s.setProperty('--yt-{k}', '{v}');" for k, v in colours.items() if valid(v))
    return f"(() => {{ const s = document.documentElement.style; {sets} }})()"
