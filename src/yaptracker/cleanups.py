"""One-time clean-ups of lines that were never chat, each with a backup first."""

import logging
from collections.abc import Callable
from pathlib import Path

from yaptracker.parser import is_input_hint
from yaptracker.store.backups import before_merge

log = logging.getLogger(__name__)


def normalise_places_once(store, backups: Path, done: Callable[[], bool],
                          save: Callable[[], object]) -> int:  # fmt: skip
    """Matches from before #276 keep hero select's raw readings ("3 COLO SEO", a map read as
    the mode): through the game lists once, what still matches nothing cleared (#435).
    Returns how many matches changed."""
    from yaptracker import game_lists

    if done():
        return 0
    changes = []
    for match_id, raw_map, raw_mode in store.match_places():
        now = (game_lists.map_name(raw_map), game_lists.queue(raw_mode))
        if now != (raw_map, raw_mode):
            changes.append((match_id, *now))
    if changes:
        before_merge(store.backup_to, backups, "cleanup")
        for match_id, map_name, mode in changes:
            store.set_match_place(match_id, map_name, mode)
        log.info("normalised map and mode of %d older match(es) (#435)", len(changes))
    save()
    return len(changes)


def remove_empty_lines_once(store, backups: Path, done: Callable[[], bool],
                            save: Callable[[], object]) -> int:  # fmt: skip
    """Lines stored without any text (#424): a callout whose message row wasn't read yet, or
    "[Name]:". Removed once, with players only they made. Returns how many lines went."""
    if done():
        return 0
    ids = store.empty_lines()
    if ids:
        before_merge(store.backup_to, backups, "cleanup")
        players = store.remove_lines(ids)
        log.info("removed %d stored line(s) without text and %d player(s) only they made (#424)",
                 len(ids), players)  # fmt: skip
    save()
    return len(ids)


def remove_input_hints_once(store, backups: Path, done: Callable[[], bool],
                            save: Callable[[], object]) -> int:  # fmt: skip
    """The chat field's hint stored as a line ("Match: PRESS TAB TO CYCLE CHANNELS", #422):
    removed once, with players only it made. Returns how many lines went."""
    if done():
        return 0
    ids = [i for i, text in store.lines_like("%CYCLE%") if is_input_hint(text)]
    if ids:
        before_merge(store.backup_to, backups, "cleanup")
        players = store.remove_lines(ids)
        log.info("removed %d stored chat field hint(s) and %d player(s) only they made (#422)",
                 len(ids), players)  # fmt: skip
    save()
    return len(ids)


def close_open_gaps(store) -> None:
    """Gaps a killed run left open (#463), closed at start; never stops the start."""
    try:
        if closed := store.close_open_gaps():
            log.warning("closed %d gap(s) left open by a run that was killed", closed)
    except Exception:
        log.exception("closing old gaps failed")
