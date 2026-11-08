"""Translate a chat line with DeepL API Free (#263, #468): opt-in, the user's own key.

The second network call the app may make (CLAUDE.md, local-only exception): one POST to
api-free.deepl.com with the line's text and the target language. Never a name, a picture, an
id or anything else. Off by default; the key lives only in the local config.json. Errors come
back as words for the line, never as a retry loop. Translations stay in memory for this run
(storing them is #470).
"""

import json
import logging
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

NO_KEY = "Add your DeepL API Free key in Settings → Translate chat first."
NOT_FREE = "That isn't a DeepL API Free key (those end in :fx)."
WRONG_KEY = "DeepL didn't accept the key. Check it in Settings → Translate chat."
QUOTA = "This month's free DeepL characters are used up."
TOO_MANY = "DeepL says too many requests. Try again in a minute."
OFFLINE = "Can't reach DeepL right now (offline?)."
FAILED = "DeepL couldn't translate this line."


@dataclass(frozen=True)
class Translation:
    text: str | None = None  # the translation; None when it failed
    source: str | None = None  # "Polish", from DeepL's detected_source_language
    error: str | None = None  # what went wrong, in words for under the line


def language(code: str | None) -> str | None:
    return LANGUAGES.get((code or "").upper().split("-")[0], code or None)


def request(key: str, text: str, target: str) -> urllib.request.Request:
    """The one request: only the line's text and the target language (#468)."""
    body = json.dumps({"text": [text], "target_lang": _TARGET_CODES.get(target, "EN-US")})
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

    def translate(self, text: str) -> Translation:
        key, target = (self._key() or "").strip(), self._target()
        if not key:
            return Translation(error=NO_KEY)
        if not key.endswith(":fx"):
            return Translation(error=NOT_FREE)
        with self._lock:
            known = self._done.get((text, target))
        if known is not None:
            return known
        try:
            found = self._send(request(key, text, target))["translations"][0]
            done = Translation(found["text"], language(found.get("detected_source_language")))
        except urllib.error.HTTPError as error:
            log.info("translate: DeepL said %s", error.code)
            return Translation(error=_HTTP.get(error.code, FAILED))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            log.info("translate: DeepL not reached (%s)", type(error).__name__)
            return Translation(error=OFFLINE)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            log.info("translate: odd answer from DeepL (%s)", type(error).__name__)
            return Translation(error=FAILED)
        with self._lock:
            self._done[(text, target)] = done
        return done


class FakeTranslator:
    """--dev and tests: no key, no network (#468)."""

    def translate(self, text: str) -> Translation:
        return Translation(f"(made-up translation of) {text}", "Spanish")
