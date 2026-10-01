"""Your data leaves the app (#31): yappers with verdicts and notes as Markdown and JSON.

Open formats on purpose: players.md reads well in any notes app, players.json is for scripts.
The full export (#69) puts the same player records next to sessions, matches and messages.
"""

import json
from datetime import datetime
from pathlib import Path

from yaptracker import __version__
from yaptracker.store.repo import Store

FORMAT_VERSION = 1
VERDICT_LABELS = {"friend": "Bestie", "fun": "Fun", "neutral": "Meh", "avoid": "Nope"}


def iso(ts: float | None) -> str | None:
    """ISO 8601 with the PC's time zone, e.g. 2026-10-01T20:05:00+02:00."""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds") if ts else None


def player_records(store: Store) -> list[dict]:
    """Every player, in id order (stable, so two exports can be diffed)."""
    return [
        {
            "id": p.id,
            "display_name": p.display_name,
            "verdict": p.verdict,  # friend / fun / neutral / avoid, or null
            "notes": p.notes or "",
            "first_met": iso(p.first_seen),
            "last_met": iso(p.last_seen),
            "aliases": store.aliases(p.id),
            "matches": p.matches,
            "messages": p.yaps,
            "flagged_messages": p.spicy,
        }
        for p in sorted(store.players(), key=lambda p: p.id)
    ]


def players_json(records: list[dict], now: float) -> str:
    return json.dumps(
        {
            "format": "yaptracker-players",
            "format_version": FORMAT_VERSION,
            "exported_at": iso(now),
            "app_version": __version__,
            "players": records,
        },
        ensure_ascii=False,
        indent=2,
    )


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "es" if word.endswith("ch") else "s")


def players_markdown(records: list[dict], now: float) -> str:
    """One section per player, A to Z: verdict, when you met, how much they said, your notes."""
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    out = [f"# Yappers\n\nExported {day} from YapTracker {__version__}: {len(records)} yappers.\n"]
    for p in sorted(records, key=lambda p: p["display_name"].casefold()):
        out.append(f"## {p['display_name']}\n")
        facts = [f"- Verdict: {VERDICT_LABELS.get(p['verdict'], 'none yet')}"]
        met = (p["last_met"] or "")[:10]
        if met:
            facts.append(f"- Last met: {met} (first: {(p['first_met'] or met)[:10]})")
        facts.append(f"- {_count(p['matches'], 'match')} together, {_count(p['messages'], 'yap')}")
        if p["aliases"]:
            facts.append(f"- Also read as: {', '.join(p['aliases'])}")
        out.append("\n".join(facts) + "\n")
        if p["notes"].strip():
            out.append(p["notes"].strip() + "\n")
    return "\n".join(out)


def export_players(store: Store, folder: Path, now: float) -> list[Path]:
    """players.md and players.json into `folder`; a second export the same day replaces them."""
    folder.mkdir(parents=True, exist_ok=True)
    records = player_records(store)
    files = {
        "players.md": players_markdown(records, now),
        "players.json": players_json(records, now),
    }
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    return [folder / name for name in files]


def export_folder(base: Path, now: float) -> Path:
    return base / f"export-{datetime.fromtimestamp(now):%Y-%m-%d}"
