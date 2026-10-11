"""One-time clean-ups of lines that were never chat, each with a backup first."""

import logging
from collections.abc import Callable
from pathlib import Path

from yaptracker.parser import is_input_hint
from yaptracker.store.backups import before_merge

log = logging.getLogger(__name__)


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
