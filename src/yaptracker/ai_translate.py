"""Translate chat with an AI model via OpenRouter (#568): understands gamer slang, typos and in-game
jargon far better than DeepL ("majeur et vacine" -> "Major and vaccine"). Opt-in, the user's own
OpenRouter key, off by default (Settings -> Translate chat -> AI).

What goes out is what DeepL gets (CLAUDE.md, Local-only): the text of the lines to translate and
the text of the few lines before as context; never names, ids or pictures. Only providers that
keep nothing (OpenRouter's zero-data-retention routing, `zdr`) are asked, none that train on it,
and not Google Vertex, whose endpoints keep flagged prompts ("Safety Retention", #583).
Live is fine: it's a network call, no work on this PC. A monthly spend cap (in US dollars,
OpenRouter's currency) stops it in words; a failed or capped request goes to DeepL when a DeepL
key is there (`Engines`).
"""

import http.client
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from yaptracker.translate import SHORT, TARGETS, Translation, Usage, language, only_shorthand

log = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/v1/chat/completions"
# Picked with a slang eval (#583, 2026-11-23): natural gamer tone, 1.3 s at the slowest, $0.10 /
# $0.50 per million tokens in / out (about $0.02 for 1,000 lines). Its zero-retention endpoint is
# Amazon Bedrock. The fallback (best on hard slang, a bit slower) steps in on its own when the
# default has no endpoint free; only for the default: a model the user picked fails in words.
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
FALLBACK_MODEL = "deepseek/deepseek-v4-flash"
# `zdr` alone still lets endpoints with Google's "Safety Retention" through (Google keeps prompts
# its classifiers flag, up to 90 days): on OpenRouter's list (2026-11-23) only Google Vertex has
# them, and there is no request field to leave them out, so that provider is skipped (#583).
PROVIDER = {"zdr": True, "data_collection": "deny", "ignore": ["google-vertex"]}
DEFAULT_CAP = 1.0  # US dollars a month
TIMEOUT_S, TIMEOUT_MAX_S = 3.0, 6.0  # a few lines answer in under a second; a batch gets more
THINKING_TIMEOUT_S = 15.0  # a model that must think first takes seconds (#568)
# A request that timed out is still billed: counted as the last cost per line seen, or this.
UNKNOWN_COST = 0.001  # US dollars, a generous guess for a small model

NO_KEY = "Add your OpenRouter key in Settings → Translate chat first."
WRONG_KEY = "OpenRouter didn't accept the key. Check it in Settings → Translate chat."
NO_CREDIT = "OpenRouter says the key has no credit left."
NO_ZDR = "No provider that keeps nothing offers this model: pick another in Settings."
BUSY = "OpenRouter says too many requests. Try again in a minute."
OFFLINE = "Can't reach OpenRouter right now (offline or slow)."
FAILED = "The AI couldn't translate this line."
_HTTP = {401: WRONG_KEY, 402: NO_CREDIT, 404: NO_ZDR, 429: BUSY}


def capped(cap: float) -> str:
    return f"This month's AI limit (${cap:.2f}) is reached: raise it in Settings → Translate chat."


def prompt(target: str) -> str:
    lang = TARGETS.get(target, "English")
    return (
        f"You translate Overwatch 2 text chat into {lang}. Players type fast: slang, typos, "
        "abbreviations, insults, jokes, hero and map names. Give what the player means, the way "
        f"a {lang}-speaking gamer would say it. Read misspelled words as the word the player "
        "meant first; a set phrase or idiom becomes its natural equivalent, never a word-by-word "
        "translation. Keep hero names, map names and gamer shorthand (gg, ez, wp, lol) as "
        'they are. Answer only with JSON: {"t": [{"l": "<the line\'s language, ISO 639-1>", '
        '"x": "<translation>"}]}, one entry per numbered line, in order. If a line is already '
        f'{lang}, its "x" is "=". The chat before is context only: don\'t translate it.'
    )


# Thinking first makes an answer slower and dearer; models that must think get little of it and
# keep it out of the answer, with room in the budget for it.
NO_THINKING = {"enabled": False}
LITTLE_THINKING = {"effort": "low", "exclude": True}


def request(key: str, model: str, texts: list[str], target: str, context: str | None = None,
            thinking: dict = NO_THINKING) -> urllib.request.Request:  # fmt: skip
    """The one request: the lines' texts, numbered, and the text of the lines before. Only
    zero-data-retention providers that don't collect data, never Google Vertex (#568, #583)."""
    lines = "\n".join(f"{n}. {' '.join(text.split())}" for n, text in enumerate(texts, start=1))
    asked = f"Chat before:\n{context}\n\nLines:\n{lines}" if context else f"Lines:\n{lines}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt(target)},
            {"role": "user", "content": asked},
        ],  # fmt: skip
        "provider": PROVIDER,
        "usage": {"include": True},  # what it cost, for the monthly cap
        "temperature": 0.2,
        "reasoning": thinking,
        "max_tokens": (120 if thinking is NO_THINKING else 1000) + 80 * len(texts),
    }
    if model == DEFAULT_MODEL:
        body["models"] = [DEFAULT_MODEL, FALLBACK_MODEL]  # OpenRouter tries them in order
    return urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "YapTracker",
        },
    )


def parse(content: str, texts: list[str], target: str) -> list[Translation]:
    """The model's JSON (also inside a code fence) as one Translation per line. "=": already in
    the target language, given back unchanged so it's remembered as nothing to translate."""
    if not isinstance(content, str):  # no text at all (cut off while thinking, a list of parts)
        raise ValueError("no text in the answer")
    start, end = content.find("{"), content.rfind("}")
    found = json.loads(content[start : end + 1])["t"]
    if not isinstance(found, list) or len(found) != len(texts):
        raise ValueError(f"answers for {len(texts)} lines: {found!r:.80}")
    out = []
    for text, item in zip(texts, found, strict=True):
        if not isinstance(item.get("x"), str):  # null or a number: never stored as a translation
            raise ValueError("an answer without text")
        said, code = item["x"].strip(), (str(item.get("l") or "").upper()[:2] or None)
        if said in ("=", "") or said == text:
            out.append(Translation(text, language(target), code=target))
        else:
            out.append(Translation(said, language(code), code=code))
    return out


def _open(req: urllib.request.Request, timeout: float) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


class Spend:
    """What the AI cost this month, in US dollars (#568), in the data folder: the cap holds
    across restarts. A new month starts at 0."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path, self._clock = path, clock
        self._lock = threading.Lock()

    def _month(self) -> str:
        return time.strftime("%Y-%m", time.localtime(self._clock()))

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("month") == self._month() else {}

    def used(self) -> float:
        with self._lock:
            return float(self._read().get("usd", 0.0))

    def add(self, usd: float) -> None:
        with self._lock:
            data = {"month": self._month(), "usd": float(self._read().get("usd", 0.0)) + usd}
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                spare = self._path.with_suffix(".tmp")
                spare.write_text(json.dumps(data), encoding="utf-8")
                os.replace(spare, self._path)
            except OSError as error:  # the next request tries again; the cap is a guide
                log.warning("translate: AI spend not saved (%s)", type(error).__name__)


class OpenRouter:
    """Translates on the caller's thread, like DeepL. Each text once a run."""

    def __init__(self, key: Callable[[], str], target: Callable[[], str],
                 model: Callable[[], str], cap: Callable[[], float], spend: Spend,
                 send: Callable[..., dict] = _open) -> None:  # fmt: skip
        self._key, self._target, self._model, self._cap = key, target, model, cap
        self.spend, self._send = spend, send
        self._lock = threading.Lock()
        self._done: dict[tuple[str, str], Translation] = {}
        # One request at a time, the cap checked and the spend counted inside: the auto thread
        # and a click can't both slip under the limit (#568). Also guards _thinks and _per_line.
        self._sending = threading.Lock()
        self._thinks: set[str] = set()  # models that can't answer without thinking first
        self._per_line: float | None = None  # what a line cost last time, for a lost answer

    def _ask(self, key: str, model: str, texts: list[str], target: str, context: str | None,
             timeout: float) -> dict:  # fmt: skip
        """Without thinking; a model that refuses that (400) is asked again with a little, and
        from then on (#568)."""
        if model not in self._thinks:
            try:
                return self._send(request(key, model, texts, target, context), timeout)
            except urllib.error.HTTPError as error:
                if error.code != 400 or b"easoning" not in (error.read() or b""):
                    raise
                log.info("translate: the AI model has to think first: asked again with a little")
                self._thinks.add(model)
        thinking = request(key, model, texts, target, context, LITTLE_THINKING)
        return self._send(thinking, max(timeout, THINKING_TIMEOUT_S))

    def usage(self, ask: bool = True) -> Usage | None:
        return None  # DeepL's characters: nothing to pause here, the spend cap does that

    def translate(self, text: str, context: str | None = None) -> Translation:
        return self.translate_many([text], context)[0]

    def translate_many(self, texts: list[str], context: str | None = None) -> list[Translation]:
        key, target = (self._key() or "").strip(), self._target()
        if not key:
            return [Translation(error=NO_KEY)] * len(texts)
        with self._lock:
            new = list(dict.fromkeys(t for t in texts if (t, target) not in self._done
                                     and not only_shorthand(t)))  # fmt: skip
        if new:
            with self._sending:
                failed = self._translate_new(key, target, new, context)
            if failed is not None:
                return [Translation(error=SHORT) if only_shorthand(t) else failed for t in texts]
        with self._lock:
            return [Translation(error=SHORT) if only_shorthand(t)
                    else self._done.get((t, target)) or Translation(error=FAILED)
                    for t in texts]  # fmt: skip

    def _translate_new(self, key: str, target: str, new: list[str],
                       context: str | None) -> Translation | None:  # fmt: skip
        """One request for `new`; None when it worked, else what went wrong (for each line)."""
        cap = self._cap()
        if self.spend.used() >= cap:
            return Translation(error=capped(cap))
        timeout = min(TIMEOUT_MAX_S, TIMEOUT_S + 0.1 * len(new))
        try:
            answer = self._ask(key, self._model(), new, target, context, timeout)
            cost = float((answer.get("usage") or {}).get("cost") or 0.0)
            self.spend.add(cost)
            self._per_line = cost / len(new) if cost else self._per_line
            done = parse(answer["choices"][0]["message"]["content"], new, target)
        except urllib.error.HTTPError as error:
            log.info("translate: OpenRouter said %s", error.code)
            return Translation(error=_HTTP.get(error.code, FAILED))
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as error:  # fmt: skip
            log.info("translate: OpenRouter not reached (%s)", type(error).__name__)
            if isinstance(error, TimeoutError) or "timed out" in str(error):  # billed anyway
                guess = self._per_line * len(new) if self._per_line else UNKNOWN_COST
                self.spend.add(guess)
            return Translation(error=OFFLINE)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            log.info("translate: odd answer from the AI (%s)", type(error).__name__)
            return Translation(error=FAILED)
        with self._lock:
            self._done.update(((t, target), d) for t, d in zip(new, done, strict=True))
        return None


class Engines:
    """Settings -> Translate chat -> DeepL / AI (#568). With AI, what it can't do (no key, the
    cap, offline, a slow answer) goes to DeepL when a DeepL API Free key is there, and DeepL's
    month isn't near its limit (#567: what's left of it is for clicks). When DeepL can't either,
    the AI's own reason stays under the line."""

    def __init__(self, deepl, ai: OpenRouter, engine: Callable[[], str],
                 has_deepl: Callable[[], bool]) -> None:  # fmt: skip
        self.deepl, self.ai, self._engine, self._has_deepl = deepl, ai, engine, has_deepl

    @property
    def name(self) -> str:
        return "the AI" if self._engine() == "ai" else "DeepL"

    def usage(self, ask: bool = True) -> Usage | None:
        """DeepL's month, which pauses auto-translate near its limit; with AI the cap does."""
        return None if self._engine() == "ai" else self.deepl.usage(ask)

    def translate(self, text: str, context: str | None = None) -> Translation:
        return self.translate_many([text], context)[0]

    def translate_many(self, texts: list[str], context: str | None = None) -> list[Translation]:
        if self._engine() != "ai":
            return self.deepl.translate_many(texts, context)
        found = self.ai.translate_many(texts, context)
        failed = [i for i, t in enumerate(found) if t.error and not only_shorthand(texts[i])]
        if not failed or not self._has_deepl():
            return found
        usage = self.deepl.usage(ask=False)
        if usage is not None and usage.near:
            return found
        log.info("translate: AI failed (%s): %d line(s) to DeepL instead", found[failed[0]].error,
                 len(failed))  # fmt: skip
        again = self.deepl.translate_many([texts[i] for i in failed], context)
        for i, translation in zip(failed, again, strict=True):
            if not translation.error:  # DeepL failing too: the AI's reason is the one to see
                found[i] = translation
        return found
