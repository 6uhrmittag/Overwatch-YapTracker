"""Foreign lines translate themselves (#469): a background thread looks at the lines stored since
its last look, once a second, and sends every line that isn't clearly in a language you read to
DeepL (#567: the local check missed most real ones), together in one request. Never on the
capture or OCR path: it only reads the database and waits for the network, and its CPU shows as
"translate" in the per-thread CPU line (#302).

Only other players' typed lines: not your own or your crew's (#74), not system lines or
callouts (the game's own words), not shorthand or single short words (`why_not`). DeepL's
detected language has the last word: a line it calls English (or another language you read), or
gives back as it was, stays untranslated and is remembered as looked at. Each text is sent once
a run; when DeepL fails (quota, key, offline) the clearly foreign lines show why, and new ones
wait a while instead of asking again and again. Near the month's free limit nothing is sent by
itself any more: what's left is for clicks. A translation is stored with its line (#470). DeepL
gets the text of the few lines before as context (#538): one request per match.
"""

import logging
import re
import threading
import time
from collections.abc import Callable

from yaptracker import ai_translate, hero_switches, languages
from yaptracker.glyphs import GLYPH, unnamed
from yaptracker.translate import (
    NO_KEY,
    NOT_FREE,
    OFFLINE,
    TOO_MANY,
    WRONG_KEY,
    Translation,
)

log = logging.getLogger(__name__)

POLL_S = 1.0  # how often it looks for new lines: the translation is there within ~1-2 s
BATCH = 25  # lines in one request at most
# After a failed request, new lines wait instead of asking again: a minute (a fixed key works a
# minute later), 10 for the rest (quota). No key yet sent nothing, so nothing waits.
WAIT_S = {OFFLINE: 60.0, TOO_MANY: 60.0, WRONG_KEY: 60.0, NO_KEY: 0.0, NOT_FREE: 0.0,
          ai_translate.OFFLINE: 60.0, ai_translate.BUSY: 60.0, ai_translate.WRONG_KEY: 60.0,
          ai_translate.NO_KEY: 0.0}  # fmt: skip
# The game's own rows that OCR sometimes glues onto the end of a typed line, names in them
# ("gg You endorsed Name!", "Name switched to Ana (was Mercy)."): cut before anything is sent.
# Only the game's own shapes at the very end: "he endorsed me lol" is somebody talking.
_SYSTEM_TAIL = re.compile(
    r"\s*(?:\S+\s+endorsed[\s-]+\S+!"  # "You endorsed Name!" (also misread "endorsed-Name!")
    r"|\S+\s+started playing Overwatch\.?)\s*$",
    re.IGNORECASE,
)
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
    return outgoing(text)


def outgoing(text: str) -> str:
    """A line's text as a translator gets it (#568): icons out, a glued system row with a name
    cut off (_SYSTEM_TAIL)."""
    plain = " ".join(unnamed(text or "").replace(GLYPH, " ").split())
    if hero_switches.find(plain):  # "Name switched to Ana (was Mercy).": two real heroes (#262)
        before = plain[: plain.rfind(" switched to ")]  # ends with the switcher's name
        plain = before.rsplit(" ", 1)[0] if " " in before else ""
    return _SYSTEM_TAIL.sub("", plain)


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
        """One look: the new lines, the foreign ones translated. Returns how many were sent.
        In named steps since #311."""
        store, translator = self._store(), self._translator()
        if store is None or translator is None:
            return 0
        lines = self._new_lines(store)
        if not lines:
            return 0
        read = self._read()
        foreign = _to_send(lines, read)
        if not foreign:
            return 0
        usage = translator.usage()
        if usage is not None and usage.near:  # the rest of the month is for clicks
            log.debug("translate: %d line(s) not sent: %d of %d characters used this month",
                      len(foreign), usage.used, usage.limit)  # fmt: skip
            return 0
        foreign, done, sent = self._send(store, translator, foreign)
        translated = self._keep(store, foreign, done, read)
        if sent:  # the evening line counts these (#567, evenings._EVENTS)
            log.info("translate: auto: %d translated of %d line(s) sent", translated, sent)
        return len(foreign)

    def _new_lines(self, store) -> list:
        """The lines stored since the last look; none just after switching on (from now on)."""
        if not self._on():
            self._last = None  # switched off: what was said meanwhile stays as it is
            return []
        lines = store.messages_after(self._last, BATCH)
        if self._last is None:  # just switched on: from now on
            self._last = lines[-1].id if lines else 0
            return []
        if lines:
            self._last = lines[-1].id
        return lines

    def _send(self, store, translator, foreign: list) -> tuple[list, list, int]:
        """One request per match: DeepL takes one context per request (#538). Returns the lines
        in the order of the answers, the answers, and how many were really sent."""
        groups: dict = {}
        for message in foreign:
            groups.setdefault(message.match_id, []).append(message)
        ordered, done, sent = [m for g in groups.values() for m in g], [], 0
        for group in groups.values():
            failed = self._failed
            if failed is not None and self._clock() < failed[0]:
                done += [failed[1]] * len(group)  # still failing: say so, don't ask again yet
                log.debug("translate: %d line(s) not sent: %s failed a moment ago", len(group),
                          getattr(translator, "name", "DeepL"))  # fmt: skip
                continue
            for message in group:
                log.debug("translate: a line of %d characters sent", len(message.text))
            sent += len(group)
            found = translator.translate_many([outgoing(m.text) for m in group],
                                              context_for(store, group[0]))  # fmt: skip
            errors = [d for d in found if d.error]
            self._failed = (
                (self._clock() + WAIT_S.get(errors[0].error, WAIT_OTHER_S), errors[0])
                if errors else None
            )  # fmt: skip
            done += found
        return ordered, done, sent

    def _keep(self, store, foreign: list, done: list, read: set[str]) -> int:
        """Each answer stored with its line or remembered as nothing to translate; what's worth
        a word under a line is shown. Returns how many were translated."""
        translated, target = 0, self._target()
        for message, translation in zip(foreign, done, strict=True):
            if translation.error:  # said under the line only when it's clearly foreign
                show = languages.foreign(unnamed(message.text), read) is not None
            elif translation.code in read or unchanged(message.text, translation.text):
                show = False  # nothing to translate: remembered, never sent again (#567)
                if translation.code:
                    store.set_not_foreign(message.id, translation.code, target)
            else:
                show, translated = True, translated + 1
                store.set_translation(message.id, translation.text, translation.code, target)
            if show:
                with self._lock:
                    self._found[message.id] = translation
        return translated

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


def _to_send(lines: list, read: set[str]) -> list:
    """The lines worth a translator's look; one debug line per decision: lengths and reasons
    only (#567)."""
    foreign = []
    for message in lines:
        why = why_not(message, read)
        if why is None:
            foreign.append(message)
        else:
            log.debug("translate: a line of %d characters not sent: %s", len(message.text), why)
    return foreign


def why_not(message, read: set[str]) -> str | None:
    """Why a line isn't sent by itself, or None: send it (#567). Who said it, whether it was
    looked at before, and the language check: nothing here knows which engine translates."""
    if message.channel == "system" or message.hero:
        return "the game's own words"
    if message.role in ("me", "crew"):
        return "yours or your crew's"
    if message.translation or message.translation_from:
        return "looked at before"
    return languages.skip(outgoing(message.text), read)  # what would be sent (#568)


def unchanged(text: str, translation: str | None) -> bool:
    """DeepL gave the line back as it was (a hero's name, a misread word, English taken for
    Dutch), but for capitals and signs: no translation."""
    return _letters(_clean(text)) == _letters(translation or "")


def _letters(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _theirs_or_mine(message) -> bool:
    """Typed by a player: the game's own lines (system, comms wheel) never go as context."""
    return message.channel != "system" and not message.hero
