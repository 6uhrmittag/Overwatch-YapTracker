"""Foreign lines translate themselves (#469): a background thread looks at the lines stored since
its last look, once a second, and sends those confidently in a language you don't read to DeepL,
together in one request. Never on the capture or OCR path: it only reads the database and waits
for the network, and its CPU shows as "translate" in the per-thread CPU line (#302).

Only other players' typed lines: not your own or your crew's (#74), not system lines or
callouts (the game's own words). DeepL's detected language has the last word: a line it calls
English (or another language you read) stays untranslated. Each text is sent once a run; when
DeepL fails (quota, key, offline) the lines show why, and new ones wait a while instead of
asking again and again. A translation is stored with its line (#470).
"""

import logging
import threading
import time
from collections.abc import Callable

from yaptracker import languages
from yaptracker.translate import NO_KEY, NOT_FREE, OFFLINE, TOO_MANY, WRONG_KEY, Translation

log = logging.getLogger(__name__)

POLL_S = 1.0  # how often it looks for new lines: the translation is there within ~1-2 s
BATCH = 25  # lines in one request at most
# After a failed request, new lines wait instead of asking again: a minute (a fixed key works a
# minute later), 10 for the rest (quota). No key yet sent nothing, so nothing waits.
WAIT_S = {OFFLINE: 60.0, TOO_MANY: 60.0, WRONG_KEY: 60.0, NO_KEY: 0.0, NOT_FREE: 0.0}
WAIT_OTHER_S = 600.0


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
        foreign = [m for m in lines if _theirs(m) and languages.foreign(m.text, read)]
        if not foreign:
            return 0
        failed, target = self._failed, self._target()
        if failed is not None and self._clock() < failed[0]:
            done = [failed[1]] * len(foreign)  # still failing: say so, don't ask again yet
        else:
            done = translator.translate_many([m.text for m in foreign])
            errors = [d for d in done if d.error]
            self._failed = (
                (self._clock() + WAIT_S.get(errors[0].error, WAIT_OTHER_S), errors[0])
                if errors else None
            )  # fmt: skip
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


def _theirs(message) -> bool:
    """Typed by someone else: not you or your crew, not the game's own words."""
    return message.channel != "system" and not message.hero and message.role not in ("me", "crew")
