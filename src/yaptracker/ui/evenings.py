"""Settings -> About: Last evenings (#379). How well each evening was read, newest first, so a
real drop shows at a glance. A table, no charts (parked)."""

import time
from html import escape

from nicegui import ui

from yaptracker import runtime
from yaptracker.evenings import percent

COLUMNS = ("Evening", "Matches", "Map", "Queue", "Result", "Lines", "Unsure", "Fixed", "CPU")
EMPTY = (
    "After your first evening with Overwatch, a row shows up here: matches, maps, results and "
    "how sure the reading was."
)
HINT = (
    "One row per evening, to spot a real drop. Map and queue: of the matches I saw start at "
    "hero select. Unsure: lines I wasn't sure I read right. Fixed: lines you edited, moved or "
    "deleted. CPU: all of YapTracker, share of one core."
)


def evenings_table() -> None:
    rows = runtime.evenings.last(7) if runtime.evenings is not None else []
    ui.label("Last evenings").classes("yt-meta")
    if not rows:
        ui.label(EMPTY).classes("yt-hint").mark("evenings-empty")
        return
    head = "".join(f"<th>{name}</th>" for name in COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in _cells(e)) + "</tr>"
        for e in rows
    )
    ui.html(
        f'<div class="yt-evenings"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        sanitize=False,  # numbers and dates only, escaped
    ).mark("evenings")
    ui.label(HINT).classes("yt-hint")


def _cells(e: dict) -> tuple:
    day = time.strftime("%a %b %d", time.strptime(e["date"], "%Y-%m-%d")).replace(" 0", " ")
    return (day, e["matches"], percent(e["map"]), percent(e["queue"]), percent(e["result"]),
            e["lines"], percent(e["low"]), e["fixed"], percent(e["cpu"]))  # fmt: skip
