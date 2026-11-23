"""Which AI models keep nothing (#584): Settings -> Translate chat -> AI offers only models with at
least one zero-data-retention endpoint on OpenRouter that also doesn't keep flagged prompts
(Google's "Safety Retention") and isn't on Google Vertex, which the request skips (#583).

The list comes from OpenRouter's public endpoint list (CLAUDE.md, Local-only): one GET, no key,
nothing sent but the request; only while AI translation is on with a key, never during a match,
at most once a day, kept in the data folder. Offline or before the first fetch: the models the
#583 eval picked, so Settings always has a list.
"""

import json
import logging
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from yaptracker.ai_translate import DEFAULT_MODEL, FALLBACK_MODEL, PROVIDER

log = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/v1/endpoints/zdr"
DAY_S = 24 * 60 * 60
CACHE = "ai_models.json"
# The #583 eval (2026-11-23, 25 lines of slang): one line each, shown under the model field.
BUILT_IN = {
    DEFAULT_MODEL: "The default: natural gamer tone, about 1 s, $0.02 for 1,000 lines.",
    FALLBACK_MODEL: "Best on hard slang and cheapest, a bit slower (up to 2.5 s).",
    "openai/gpt-oss-120b": "Good, but thinks first: slower and dearer ($0.04 for 1,000 lines).",
    "mistralai/mistral-small-3.2-24b-instruct": "Solid, but slow (3-6 s a request).",
    "openai/gpt-oss-20b": "Cheap, thinks first; leaves some slang untranslated.",
    "qwen/qwen3.5-9b": "Fast, but often leaves slang untranslated.",
}


def not_kept(model: str) -> str:
    return (f"No provider that keeps nothing offers {model}: I can't translate with it. Pick one "
            "from the list.")  # fmt: skip


def fetch_list() -> dict:
    request = urllib.request.Request(URL, headers={"User-Agent": "YapTracker"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def keeps_nothing(endpoints: list) -> dict[str, str]:
    """model id -> one-line hint, for the chat models with an endpoint the request may use."""
    skipped = tuple(PROVIDER.get("ignore", ()))
    found: dict[str, tuple[float, float, str]] = {}
    for e in endpoints:
        if not isinstance(e, dict) or e.get("safety_retention") is not False:
            continue  # kept flagged prompts, or the list doesn't say: not "keeps nothing"
        model, tag = e.get("model_id"), str(e.get("tag") or "")
        params = e.get("supported_parameters") or []
        if not isinstance(model, str) or tag.split("/")[0] in skipped:
            continue
        if "max_tokens" not in params or "temperature" not in params:
            continue  # embeddings, speech, pictures: no chat
        try:
            price = (float(e["pricing"]["prompt"]) * 1e6, float(e["pricing"]["completion"]) * 1e6)
        except (KeyError, TypeError, ValueError):
            continue
        if model not in found or price < found[model][:2]:
            found[model] = (*price, str(e.get("model_name") or model))
    return {model: f"{name}: ${p_in:.2f} / ${p_out:.2f} per million tokens in / out."
            for model, (p_in, p_out, name) in sorted(found.items())}  # fmt: skip


class Models:
    """The list for Settings, fetched at most once a day; the built-in one until then."""

    def __init__(self, path: Path, fetch: Callable[[], dict] | None = None,
                 clock: Callable[[], float] = time.time) -> None:  # fmt: skip
        self._path, self._clock = path, clock
        self._fetch = fetch or (lambda: fetch_list())  # looked up when called: tests swap it
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        ok = isinstance(data, dict) and isinstance(data.get("models"), dict)
        return data if ok else {}

    def checked(self) -> bool:
        """The list is OpenRouter's, not the built-in one."""
        return bool(self._read().get("models"))

    def hints(self) -> dict[str, str]:
        """model id -> hint: the eval's words where it has them, the price otherwise."""
        models = self._read().get("models") or {}
        if not models:
            return dict(BUILT_IN)
        return {m: BUILT_IN.get(m, hint) for m, hint in models.items()}

    def problem(self, model: str) -> str | None:
        """Words for a model no provider that keeps nothing offers; None when it's fine or the
        list isn't checked yet (offline: the request itself says so, #583)."""
        if not model or not self.checked():
            return None
        return None if model in self.hints() else not_kept(model)

    def refresh(self, allowed: bool) -> bool:
        """Fetch the list when allowed (AI on, a key, no match) and a day old; True if new."""
        if not allowed:
            return False
        with self._lock:
            fetched = self._read().get("fetched")
            if isinstance(fetched, int | float) and self._clock() - fetched < DAY_S:
                return False
            try:
                models = keeps_nothing(self._fetch().get("data") or [])
            except (OSError, ValueError, AttributeError) as error:
                log.info("AI models: OpenRouter's list not fetched (%s)", type(error).__name__)
                return False
            if not models:  # an empty or odd answer never replaces a good list
                log.info("AI models: OpenRouter's list had no model that keeps nothing")
                return False
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                spare = self._path.with_suffix(".tmp")
                spare.write_text(json.dumps({"fetched": self._clock(), "models": models}),
                                 encoding="utf-8")  # fmt: skip
                os.replace(spare, self._path)
            except OSError as error:
                log.warning("AI models: list not saved (%s)", type(error).__name__)
                return False
            log.info("AI models: %d models keep nothing on OpenRouter", len(models))
            return True
