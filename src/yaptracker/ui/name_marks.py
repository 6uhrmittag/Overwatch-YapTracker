"""A small verdict mark next to known players' names in chat lines (#519), Live and transcripts.

YapTracker only knows someone is there because their name shows up in a line, so the mark on the
name reaches everyone it can know about: chat, comms wheel and system lines ("[x] started
playing", "You endorsed x!"). Known = a verdict, or met in another match ("met before" dot).
Me and my crew never get one. A click opens the familiar-face card (#518). It sits inline at a
fixed size: the line's height doesn't change.
"""

import re
import time
from collections.abc import Callable

from nicegui import ui

from yaptracker import config, runtime
from yaptracker.familiar import card_for
from yaptracker.identity import Identity
from yaptracker.ui.components import VERDICTS
from yaptracker.ui.familiar_cards import face_card, popover

MET = "met"  # known, no verdict yet: a dot
_ENDORSED = re.compile(r"^You endorsed (?P<name>.+?)!?$")
STOP = "(e) => { e.stopPropagation(); emit(); }"
FRESH_S = 5.0  # Live: who's known and their verdicts, read again at most this often


def system_name(message) -> tuple[str | None, bool]:
    """(the name a system line is about, whether it stands at its end)."""
    if message.channel != "system":
        return None, False
    if message.speaker_raw:
        return message.speaker_raw, False  # "[x] started playing Overwatch."
    found = _ENDORSED.match(message.text or "")
    return (found["name"].strip(), True) if found else (None, False)


class NameMarks:
    """Who in this match's lines is known: only the players in them are looked at, and whether
    they were met in another match is kept for the match (`before`: the last look, same match)."""

    def __init__(
        self,
        match_id: int | None,
        messages: list,
        identity: Identity | None = None,
        before: "NameMarks | None" = None,
    ):
        store = runtime.store
        self.match_id, self.read_at = match_id, time.monotonic()
        identity = identity or config.identity()
        names = store.player_names()
        mine = {pid for pid, name in names if identity.role(name) is not None}
        self._ids = {name.casefold(): pid for pid, name in names if pid not in mine}
        same = before is not None and before.match_id == match_id
        self._elsewhere: dict[int, bool] = before._elsewhere if same else {}
        verdicts = store.verdicts()
        self._kind: dict[int, str] = {}
        for pid in {self._speaker(m) for m in messages} - mine - {None}:
            if pid not in self._elsewhere:
                self._elsewhere[pid] = store.met_before(pid, match_id)[0] > 0
            if verdicts.get(pid) or self._elsewhere[pid]:
                self._kind[pid] = verdicts.get(pid) or MET

    def _speaker(self, message) -> int | None:
        if message.channel == "system":
            name, _ = system_name(message)
            return self._ids.get(name.casefold()) if name else None
        return message.player_id if message.role not in ("me", "crew") else None

    def player(self, message) -> int | None:
        """The known player a line is from or about, else None."""
        pid = self._speaker(message)
        return pid if pid in self._kind else None

    def kind(self, player_id: int | None) -> str | None:
        return self._kind.get(player_id) if player_id is not None else None

    def add(self, message) -> dict | None:
        """The mark for this line, at the current spot in the line; None for unknown ones."""
        pid = self.player(message)
        if pid is None:
            return None
        mark = ui.element("button").props('type="button"').mark(f"name-mark name-mark-{message.id}")
        holder = {"el": mark, "pid": pid, "kind": None, "match": self.match_id}
        set_kind(holder, self._kind[pid])
        # its own click: not the line's (picture, snap pick)
        mark.on("click", lambda: open_card(holder), js_handler=STOP)
        return holder


def set_kind(holder: dict, kind: str | None) -> None:
    """Show the mark as this verdict / "met before"; gone when they're not known any more."""
    if kind == holder["kind"]:
        return
    mark = holder["el"]
    if holder["kind"]:
        mark.classes(remove=f"yt-mark--{holder['kind']}")
    holder["kind"] = kind
    mark.set_visibility(kind is not None)
    if kind is None:
        return
    mark.classes(add=f"yt-mark yt-mark--{kind}")
    label = "Met before" if kind == MET else VERDICTS[kind][0]
    mark.props(f'title="{label}: what you know" aria-label="{label}"')
    mark.clear()
    if kind != MET:
        with mark:
            ui.html(f'<svg width="11" height="11" viewBox="0 0 24 24" fill="none" '
                    f'stroke="currentColor" stroke-width="3" stroke-linecap="round" '
                    f'aria-hidden="true">{VERDICTS[kind][1]}</svg>', sanitize=False)  # fmt: skip


def open_card(holder: dict, on_open: Callable[[int], None] | None = None) -> None:
    """The familiar-face card as a popover under the mark (#518); made on the click."""
    card = card_for(runtime.store, holder["pid"], holder["match"])
    if card is None:
        return
    show = on_open or (lambda pid: ui.context.client.yt_show("yappers", player_id=pid))
    with holder["el"]:
        menu = popover(None)
        with menu:
            face_card(card, lambda: show(card.player_id))
    menu.on_value_change(lambda e: None if e.value else menu.delete())  # gone once closed
    menu.open()
