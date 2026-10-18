"""Chat still waiting to be read after its match (#501), in words: Days, the day view, the
transcript and Live say so, so a half-read match never looks like missing chat."""

from collections.abc import Callable

from nicegui import ui

from yaptracker import runtime
from yaptracker.later import Backlog
from yaptracker.ui.components import count

FOLLOW_S = 2.0  # how often the badges and the banner look again
READING = "Still reading"  # the badge of what's read right now


def now() -> Backlog | None:
    """What waits right now; None when nothing does (or no reader runs)."""
    reader = runtime.reader
    found = reader.backlog() if hasattr(reader, "backlog") else None
    return found if found is not None and found.left else None


def eta(seconds: float) -> str:
    """'~4 min', 'under a minute'."""
    return f"~{max(1, round(seconds / 60))} min" if seconds >= 60 else "under a minute"


def badge(waiting: Backlog | None, match_id: int) -> str | None:
    """A match row's badge, None once it's read through."""
    state = waiting.state(match_id) if waiting else None
    if state == "reading":
        left, _ = waiting.matches[match_id]
        return f"{READING} \u00b7 {count(left, 'picture', 'pictures')} left"
    return {"after": "Read after the match", "waiting": "Waiting to be read"}.get(state)


def day_badge(waiting: Backlog | None, match_ids: tuple[int, ...]) -> str | None:
    """A day's badge: what its matches' badges say at most."""
    states = {waiting.state(m) for m in match_ids} if waiting else set()
    return READING if "reading" in states else "Waiting to be read" if states - {None} else None


def banner(waiting: Backlog | None, match_id: int) -> tuple[str, float] | None:
    """The transcript's line and how much is read (0-1); None once it's read through."""
    state = waiting.state(match_id) if waiting else None
    if state is None:
        return None
    left, read = waiting.matches[match_id]
    total = left + read
    if state == "reading":
        text = (
            f"Still reading this match's chat: {read} of {total} pictures done "
            f"({eta(waiting.seconds_left(match_id))}). New lines will keep appearing."
        )
    elif state == "after":
        text = (
            f"This match is read once it's over: {count(total, 'chat picture', 'chat pictures')}"
            " kept so far. Your FPS stays untouched."
        )
    elif waiting.deferring:
        text = (
            f"This match's chat waits to be read: {count(total, 'picture', 'pictures')}, read "
            "once the running match is over."
        )
    else:
        order = list(waiting.matches)
        ahead = sum(1 for m in order[: order.index(match_id)] if m is not None)
        after = f", after {count(ahead, 'earlier match', 'earlier matches')}" if ahead else ""
        text = (
            f"This match's chat waits to be read: {count(total, 'picture', 'pictures')}{after} "
            f"({eta(waiting.seconds_left(match_id))}). New lines will keep appearing."
        )
    return text, read / total


def live(waiting: Backlog) -> str:
    """Live's line while kept chat is read (not during a match read afterwards)."""
    pictures = count(waiting.left, "chat picture", "chat pictures")
    left = f"{count(waiting.left, 'picture', 'pictures')} left ({eta(waiting.seconds_left())})"
    if waiting.restored >= waiting.left:  # (#474)
        return f"Reading {pictures} from your last session ({eta(waiting.seconds_left())})."
    matches = [m for m in waiting.matches if m is not None]
    if not matches:
        return f"Reading the chat kept for after the match: {left}."
    whose = (
        "the last match" if matches == [waiting.match_id]
        else "an earlier match" if len(matches) == 1
        else count(len(matches), "earlier match", "earlier matches")
    )  # fmt: skip
    return f"Reading the chat of {whose}: {left}."


def during(kind: str, waiting: Backlog | None) -> str:
    """Live's line during a match read afterwards (#335): earlier ones may still wait."""
    if earlier := len(waiting.earlier()) if waiting else 0:
        matches = count(earlier, "earlier match", "earlier matches")
        return f"{kind}: read once it's over. {matches} still waiting to be read."
    return f"{kind}: reading after the match. Your FPS stays untouched."


def follow(labels: dict, say: Callable[[Backlog | None, object], str | None]) -> None:
    """Keeps badges right while the chat is read; they go once it's read through."""

    def update() -> None:
        waiting = now()
        for key, label in labels.items():
            said = say(waiting, key)
            label.set_text(said or "")
            label.classes(**{"remove" if said else "add": "yt-hidden"})
            quiet = said is not None and not said.startswith(READING)  # only that one pulses
            label.classes(**{"add" if quiet else "remove": "yt-reading--quiet"})

    update()
    ui.timer(FOLLOW_S, update)
