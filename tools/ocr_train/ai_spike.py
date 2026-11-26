"""#637 spike: vision models on OpenRouter re-read hard chat lines from their picture.

    OPENROUTER_API_KEY=... python tools/ocr_train/ai_spike.py [--lines 200]

200 hard lines of the #608 gold set (labelled by hand from the pictures): first those the app
stored wrong or the engines read differently, icon lines, umlaut lines, wrapped lines; then the
rest. Each line picture (only that, as #637 allows) goes to each model with the "transcribe
exactly" prompt, through the same zero-data-retention routing as AI translation (#583).
Prints a table: lines exact, names exact, icons named, latency, $ per line. Readings are kept
in fixtures/private/ocr/readings/ai-<model>.jsonl (private), resumable.

Costs real money on the key (a few cents for 200 lines on the small models).
"""

import argparse
import base64
import io
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import common  # noqa: E402
import score  # noqa: E402
from inventory import WRAP_HEIGHT  # noqa: E402

from yaptracker.ai_translate import PROVIDER, URL  # noqa: E402

MODELS = [
    "anthropic/claude-haiku-5.5",
    "anthropic/claude-sonnet-5.5",
    "qwen/qwen3-vl-30b-a3b-instruct",
    "mistralai/mistral-small-3.2-24b-instruct",
]
PROMPT = (
    "This picture is one row of Overwatch's in-game text chat. Transcribe it exactly, "
    "character by character: brackets, colons, punctuation, capitals, umlauts and ß as shown. "
    "Names and slang are spelled unusually on purpose: never correct spelling, never complete "
    "or translate anything. Leave out the small channel icon at the very start of the row. "
    "Where the row shows an emoji or a game icon, write ◇ in its place. "
    'Answer with JSON only: {"text": "<the row>", "icons": ["<what each ◇ shows, 1-3 words>"]}'
)
WORKERS = 4
THINKS = {"anthropic/claude-sonnet-5.5"}  # its endpoint refuses "no reasoning" (400)


def picture_url(path: Path) -> str:
    buffer = io.BytesIO()
    Image.open(path).convert("RGB").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def ask(key: str, model: str, path: Path) -> dict:
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": picture_url(path)}},
                ],
            }
        ],  # fmt: skip
        "provider": PROVIDER,
        "usage": {"include": True},
        "temperature": 0,
        "max_tokens": 300,
        "reasoning": {"effort": "low", "exclude": True} if model in THINKS else {"enabled": False},
    }
    request = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "X-Title": "YapTracker"},
    )  # fmt: skip
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        answer = json.load(response)
    seconds = time.perf_counter() - start
    content = answer["choices"][0]["message"]["content"] or ""
    begin = content.find("{")  # the first JSON object; some models add a second or a remark
    parsed = json.JSONDecoder().raw_decode(content[begin:])[0] if begin >= 0 else {"text": content}
    usd = float((answer.get("usage") or {}).get("cost") or 0)
    row, icons = str(parsed.get("text") or ""), parsed.get("icons") or []
    return {"row": row, "icons": icons, "s": round(seconds, 2), "usd": usd}


def hard_lines(private: Path, gold: list[dict], count: int) -> list[dict]:
    readings = {}
    for name in ("rapid", "glm", "qwen"):
        path = private / "readings" / f"{name}.jsonl"
        if path.exists():
            readings[name] = score.reread(path)
    stored = score.stored(gold)

    def hardness(g: dict) -> int:
        seen = {stored[g["id"]]} | {r[g["id"]] for r in readings.values() if g["id"] in r}
        german = g in score.buckets(gold)["DE (umlauts/ß)"]
        wrong = stored[g["id"]] != g["gold"]
        return 2 * wrong + (len(seen) > 1) + g["glyphs"] + german + (g["height"] >= WRAP_HEIGHT)

    return sorted(gold, key=hardness, reverse=True)[:count]


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--lines", type=int, default=200)
    args.add_argument("--models", nargs="*", default=MODELS)
    opts = args.parse_args()
    import os

    key = os.environ["OPENROUTER_API_KEY"]
    private = common.private()
    gold = hard_lines(private, score.load(private), opts.lines)
    lock = threading.Lock()
    for model in opts.models:
        out = private / "readings" / f"ai-{model.replace('/', '_')}.jsonl"
        kept = [json.loads(line) for line in out.open(encoding="utf-8")] if out.exists() else []
        kept = [r for r in kept if "error" not in r]  # failed ones are asked again
        out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8"
        )
        done = {r["id"] for r in kept}

        def one(g: dict, model: str = model, out: Path = out) -> None:
            try:
                got = ask(key, model, private / g["picture"])
            except (OSError, ValueError, KeyError) as error:  # URLError, timeouts, resets
                got = {"row": "", "icons": [], "s": None, "usd": 0.0, "error": repr(error)[:120]}
            with lock, out.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": g["id"], **got}, ensure_ascii=False) + "\n")

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(one, [g for g in gold if g["id"] not in done]))
    report(private, gold, opts.models)


def report(private: Path, gold: list[dict], models: list[str]) -> None:
    stored = score.stored(gold)
    print(f"{len(gold)} hard lines")
    s = score.score(gold, stored)
    print(f"{'RapidOCR, as stored':42} lines {s['exact']:6.1%}  names {s['names']:6.1%}")
    icon_lines = [g for g in gold if "[icon:" in (g["ocr_text"] or "")]
    for model in models:
        path = private / "readings" / f"ai-{model.replace('/', '_')}.jsonl"
        rows = {r["id"]: r for r in map(json.loads, path.open(encoding="utf-8"))}
        failed = sum("error" in r for r in rows.values())
        rows = {i: r for i, r in rows.items() if "error" not in r}
        part = [g for g in gold if g["id"] in rows]  # scored on what it answered
        got = {i: score.fields(r["row"]) for i, r in rows.items()}
        s = score.score(part, got)
        ok = list(rows.values())
        seconds = sorted(r["s"] for r in ok)
        usd = statistics.mean(r["usd"] for r in ok) if ok else 0.0
        named = sum(
            any(word in " ".join(map(str, rows[g["id"]]["icons"])).lower()
                for word in g["ocr_text"].split("[icon:")[1].split("]")[0].split("-"))
            for g in icon_lines if g["id"] in rows
        )  # fmt: skip
        de = score.score([g for g in score.buckets(gold)["DE (umlauts/ß)"] if g in part], got)
        print(f"{model:42} lines {s['exact']:6.1%}  names {s['names']:6.1%}  "
              f"DE lines {de['exact']:6.1%}  icons named {named}/{len(icon_lines)}  "
              f"s median {statistics.median(seconds) if seconds else 0:.2f} max "
              f"{max(seconds) if seconds else 0:.2f}  $/line {usd:.6f}  "
              f"failed {failed}, answered {len(part)}")  # fmt: skip


if __name__ == "__main__":
    main()
