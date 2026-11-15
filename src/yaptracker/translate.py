"""Translate a chat line with DeepL API Free (#263, #468): opt-in, the user's own key.

The second network call the app may make (CLAUDE.md, local-only exception): one POST to
api-free.deepl.com with the line's text and the target language, and as `context` the text of a
few lines before it (#538; DeepL reads it, doesn't translate or bill it). Never a name, a
picture, an id or anything else. Gamer shorthand alone (gg, ez...) is never sent; inside a line
it's marked for DeepL to leave as it is. Off by default; the key lives only in the local
config.json. Errors come back as words for the line, never as a retry loop. Each text is sent
once a run; translations are stored with their line (#470).
"""

import html
import http.client
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

URL = "https://api-free.deepl.com/v2/translate"
TIMEOUT_S = 10
TARGETS = {"EN": "English", "DE": "German"}  # what Settings offers
_TARGET_CODES = {"EN": "EN-US", "DE": "DE"}  # DeepL wants a variant for English
# DeepL's source languages (detected_source_language), as words for "(from Polish)".
LANGUAGES = {
    "AR": "Arabic", "BG": "Bulgarian", "CS": "Czech", "DA": "Danish", "DE": "German",
    "EL": "Greek", "EN": "English", "ES": "Spanish", "ET": "Estonian", "FI": "Finnish",
    "FR": "French", "HU": "Hungarian", "ID": "Indonesian", "IT": "Italian", "JA": "Japanese",
    "KO": "Korean", "LT": "Lithuanian", "LV": "Latvian", "NB": "Norwegian", "NL": "Dutch",
    "PL": "Polish", "PT": "Portuguese", "RO": "Romanian", "RU": "Russian", "SK": "Slovak",
    "SL": "Slovenian", "SV": "Swedish", "TR": "Turkish", "UK": "Ukrainian", "ZH": "Chinese",
}  # fmt: skip

# Gamer shorthand (#538): a line of only these is never sent; inside a line DeepL keeps them.
SHORTHAND = frozenset({
    "gg", "ggs", "ggwp", "ggez", "wp", "ez", "gl", "hf", "glhf", "gj", "nt", "ns", "ff", "xd",
    "kek", "lol", "lmao", "lmfao", "rofl", "ty", "thx", "tyvm", "np", "rip", "brb", "afk", "omg",
    "wtf", "idk", "pls", "plz", "ok", "gn",
})  # fmt: skip
_SAME = re.compile(r"(.)\1+")  # "ggggg", "xDDD", "lmaooo"
_SHORT = frozenset(_SAME.sub(r"\1", word) for word in SHORTHAND)
_KEEP = "x"  # the tag DeepL is asked to leave alone (ignore_tags)
_WORD = re.compile(r"\S+")

NO_KEY = "Add your DeepL API Free key in Settings → Translate chat first."
NOT_FREE = "That isn't a DeepL API Free key (those end in :fx)."
WRONG_KEY = "DeepL didn't accept the key. Check it in Settings → Translate chat."
QUOTA = "This month's free DeepL characters are used up."
TOO_MANY = "DeepL says too many requests. Try again in a minute."
OFFLINE = "Can't reach DeepL right now (offline?)."
FAILED = "DeepL couldn't translate this line."
SHORT = "Gamer shorthand: nothing to translate."


@dataclass(frozen=True)
class Translation:
    text: str | None = None  # the translation; None when it failed
    source: str | None = None  # "Polish", from DeepL's detected_source_language
    error: str | None = None  # what went wrong, in words for under the line
    code: str | None = None  # "PL": DeepL's language code, to compare with "I read" (#469)


def language(code: str | None) -> str | None:
    return LANGUAGES.get((code or "").upper().split("-")[0], code or None)


def _is_short(word: str) -> bool:
    letters = re.sub(r"[^0-9a-z]", "", word.casefold())
    return bool(letters) and (letters in SHORTHAND or _SAME.sub(r"\1", letters) in _SHORT)


def only_shorthand(text: str) -> bool:
    """Only shorthand ("gg ez", "GGGG!", "xD lol"): nothing for DeepL (#538). Signs and
    pictures don't count."""
    words = [w for w in text.split() if re.search(r"[0-9a-zA-Z]", w) or w.isalpha()]
    return bool(words) and all(_is_short(word) for word in words)


def _marked(text: str) -> str:
    """The line as XML for DeepL, its shorthand inside <x> so it comes back as typed."""
    return _WORD.sub(lambda m: f"<{_KEEP}>{html.escape(m[0])}</{_KEEP}>" if _is_short(m[0])
                     else html.escape(m[0]), text)  # fmt: skip


def _unmarked(text: str) -> str:
    return html.unescape(re.sub(rf"</?{_KEEP}>", "", text))


def request(key: str, texts: list[str], target: str,
            context: str | None = None) -> urllib.request.Request:  # fmt: skip
    """The one request: only the lines' texts, the target language (#468) and the text of the
    lines before them as context (#538); several lines that came in together go in one (#469)."""
    fields: dict = {"text": texts, "target_lang": _TARGET_CODES.get(target, "EN-US")}
    if any(_is_short(word) for text in texts for word in text.split()):
        fields |= {"text": [_marked(t) for t in texts], "tag_handling": "xml",
                   "ignore_tags": [_KEEP]}  # fmt: skip
    if context:
        fields["context"] = context
    body = json.dumps(fields)
    return urllib.request.Request(
        URL,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"DeepL-Auth-Key {key}",
            "Content-Type": "application/json",
            "User-Agent": "YapTracker",
        },
    )


def _open(req: urllib.request.Request) -> dict:
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return json.load(response)


_HTTP = {403: WRONG_KEY, 456: QUOTA, 429: TOO_MANY}


class DeepL:
    """Translates on the caller's thread (the UI hands it to a worker). Each text once a run."""

    def __init__(self, key: Callable[[], str], target: Callable[[], str],
                 send: Callable[[urllib.request.Request], dict] = _open) -> None:  # fmt: skip
        self._key, self._target, self._send = key, target, send
        self._lock = threading.Lock()
        self._done: dict[tuple[str, str], Translation] = {}
        self._context = True  # until DeepL turns it down once (#538)

    def translate(self, text: str, context: str | None = None) -> Translation:
        return self.translate_many([text], context)[0]

    def _ask(self, key: str, texts: list[str], target: str, context: str | None) -> dict:
        """With the context, or without it when DeepL doesn't take it: then never again."""
        if context and self._context:
            try:
                return self._send(request(key, texts, target, context))
            except urllib.error.HTTPError as error:
                if error.code != 400:
                    raise
                log.info("translate: DeepL turned the context down: sent without it from now")
                self._context = False
        return self._send(request(key, texts, target))

    def translate_many(self, texts: list[str], context: str | None = None) -> list[Translation]:
        """One request for the texts not translated yet this run; what went wrong is the same
        for each of them. Shorthand alone is never sent (#538)."""
        key, target = (self._key() or "").strip(), self._target()
        if not key or not key.endswith(":fx"):
            return [Translation(error=NO_KEY if not key else NOT_FREE)] * len(texts)
        with self._lock:
            new = list(dict.fromkeys(t for t in texts if (t, target) not in self._done
                                     and not only_shorthand(t)))  # fmt: skip
        if new:
            try:
                answer = self._ask(key, new, target, context)["translations"]
                done = [Translation(_unmarked(found["text"]),
                                    language(found.get("detected_source_language")),
                                    code=_code(found.get("detected_source_language")))
                        for found in answer]  # fmt: skip
                if len(done) != len(new):
                    raise ValueError(f"{len(done)} answers for {len(new)} lines")
            except urllib.error.HTTPError as error:
                log.info("translate: DeepL said %s", error.code)
                return [Translation(error=_HTTP.get(error.code, FAILED))] * len(texts)
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                http.client.HTTPException,
            ) as error:
                log.info("translate: DeepL not reached (%s)", type(error).__name__)
                return [Translation(error=OFFLINE)] * len(texts)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                log.info("translate: odd answer from DeepL (%s)", type(error).__name__)
                return [Translation(error=FAILED)] * len(texts)
            with self._lock:
                self._done.update(((t, target), d) for t, d in zip(new, done, strict=True))
        with self._lock:
            return [Translation(error=SHORT) if only_shorthand(t) else self._done[(t, target)]
                    for t in texts]  # fmt: skip


def _code(code: str | None) -> str | None:
    return (code or "").upper().split("-")[0] or None


class FakeTranslator:
    """--dev and tests: no key, no network (#468)."""

    def translate(self, text: str, context: str | None = None) -> Translation:
        if only_shorthand(text):
            return Translation(error=SHORT)
        return Translation(f"(made-up translation of) {text}", "Spanish", code="ES")

    def translate_many(self, texts: list[str], context: str | None = None) -> list[Translation]:
        return [self.translate(text, context) for text in texts]
