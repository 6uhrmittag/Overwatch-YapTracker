"""Foreign lines translate themselves (#469): a background thread looks at the lines stored since
its last look, once a second, and sends those confidently in a language you don't read to DeepL,
together in one request. Never on the capture or OCR path: it only reads the database and waits
for the network, and its CPU shows as "translate" in the per-thread CPU line (#302).

Only other players' typed lines: not your own or your crew's (#74), not system lines or
callouts (the game's own words). DeepL's detected language has the last word: a line it calls
English (or another language you read) stays untranslated. Each text is sent once a run; when
DeepL fails (quota, key, offline) the lines show why, and new ones wait a while instead of
asking again and again. A translation is stored with its line (#470). DeepL gets the text of
the few lines before as context (#538): one request per match.
"""

import logging
import threading
import time
from collections.abc import Callable

from yaptracker import languages
from yaptracker.glyphs import GLYPH, unnamed
from yaptracker.translate import (
    NO_KEY,
    NOT_FREE,
    OFFLINE,
    TOO_MANY,
    WRONG_KEY,
    Translation,
    only_shorthand,
)

log = logging.getLogger(__name__)

POLL_S = 1.0  # how often it looks for new lines: the translation is there within ~1-2 s
BATCH = 25  # lines in one request at most
# After a failed request, new lines wait instead of asking again: a minute (a fixed key works a
# minute later), 10 for the rest (quota). No key yet sent nothing, so nothing waits.
WAIT_S = {OFFLINE: 60.0, TOO_MANY: 60.0, WRONG_KEY: 60.0, NO_KEY: 0.0, NOT_FREE: 0.0}
WAIT_OTHER_S = 600.0
CONTEXT_LINES = 5  # lines before as DeepL's context (#538): the same channel's first
CONTEXT_SAME = 3  # fewer of those than this: the match's lines of any channel


def context_for(store, message) -> str | None:
    """The text of the few lines said before `message` in its match: only their text, never a
    name or an id, and never the game's own lines (system lines carry names)."""
    if store is None or getattr(message, "match_id", None) is None:
        return None
    before = [m for m in store.messages(message.match_id)
              if m.id < message.id and _theirs_or_mine(m) and _clean(m.text)]  # fmt: skip
    same = [m for m in before if m.channel == message.channel]
    lines = same[-CONTEXT_LINES:] if len(same) >= CONTEXT_SAME else before[-CONTEXT_LINES:]
    return "\n".join(_clean(m.text) for m in lines) or None


def _clean(text: str) -> str:
    return " ".join(unnamed(text or "").replace(GLYPH, " ").split())


class AutoTranslate:
    def __init__(
        self,
        store: Callable[[], object],
        translator: Callable[[], object],
        on: Callable[[], bool],
        read: Callable[[], set[str]],
        clock: Callable[[], float] = time.monotonic,
        target: Callable[[], str] = lambda: "EN",
    ) -> None:
        self._store, self._translator, self._on, self._read = store, translator, on, read
        self._target = target  # the language translated into, stored with the line (#470)
        self._clock = clock
        self._last: int | None = None  # the newest line looked at
        self._found: dict[int, Translation] = {}  # message id -> translation, or why not
        self._failed: tuple[float, Translation] | None = None  # until when, and why
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def known(self, message_id: int) -> Translation | None:
        """The translation to show under a line, or what went wrong; None: nothing to show."""
        with self._lock:
            return self._found.get(message_id)

    def step(self) -> int:
        """One look: the new lines, the foreign ones translated. Returns how many were sent."""
        store, translator = self._store(), self._translator()
        if store is None or translator is None:
            return 0
        if not self._on():
            self._last = None  # switched off: what was said meanwhile stays as it is
            return 0
        lines = store.messages_after(self._last, BATCH)
        if self._last is None:  # just switched on: from now on
            self._last = lines[-1].id if lines else 0
            return 0
        if not lines:
            return 0
        self._last = lines[-1].id
        read = self._read()
        foreign = [m for m in lines if _theirs(m) and not only_shorthand(unnamed(m.text))
                   and languages.foreign(unnamed(m.text), read)]  # fmt: skip
        if not foreign:
            return 0
        groups: dict = {}  # one request per match: DeepL takes one context per request (#538)
        for message in foreign:
            groups.setdefault(message.match_id, []).append(message)
        foreign, done, target = [m for g in groups.values() for m in g], [], self._target()
        for group in groups.values():
            failed = self._failed
            if failed is not None and self._clock() < failed[0]:
                done += [failed[1]] * len(group)  # still failing: say so, don't ask again yet
                continue
            found = translator.translate_many([unnamed(m.text) for m in group],
                                              context_for(store, group[0]))  # fmt: skip
            errors = [d for d in found if d.error]
            self._failed = (
                (self._clock() + WAIT_S.get(errors[0].error, WAIT_OTHER_S), errors[0])
                if errors else None
            )  # fmt: skip
            done += found
        with self._lock:
            for message, translation in zip(foreign, done, strict=True):
                if translation.error or translation.code not in read:
                    self._found[message.id] = translation
        for message, translation in zip(foreign, done, strict=True):
            if not translation.error and translation.code not in read:
                store.set_translation(message.id, translation.text, translation.code, target)
        log.info("translate: %d line(s) to DeepL, %d translated", len(foreign),
                 sum(1 for d in done if not d.error and d.code not in read))  # fmt: skip
        return len(foreign)

    def start(self) -> None:
        threading.Thread(target=self._run, name="translate", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self.step()
            except Exception:  # never takes the app down; tried again in a second
                log.exception("translate: looking at new lines failed")


def _theirs_or_mine(message) -> bool:
    """Typed by a player: the game's own lines (system, comms wheel) never go as context."""
    return message.channel != "system" and not message.hero


def _theirs(message) -> bool:
    """Typed by someone else: not you or your crew, not the game's own words."""
    return message.channel != "system" and not message.hero and message.role not in ("me", "crew")
