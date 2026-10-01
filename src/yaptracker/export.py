"""Your data leaves the app: yappers as Markdown and JSON (#31), everything as JSON (#69).

Open formats on purpose: players.md reads well in any notes app, the JSON files are for scripts.
The full export puts the same player records next to sessions, matches, messages and gaps; its
format is documented in docs/export-format.md and docs/export.schema.json.
"""

import json
import textwrap
from collections.abc import Callable, Iterable
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


def _message(m) -> dict:
    return {
        "id": m.id,
        "time": iso(m.ts),
        "channel": m.channel,
        "speaker": m.speaker_raw,
        "player_id": m.player_id,
        "role": m.role,  # me / crew / null
        "hero": m.hero,
        "text": m.text,
        "ocr_confidence": m.ocr_confidence,
        "flagged": m.flagged,  # overwatch ([Report] link) / manual / null (#77)
        "has_glyphs": bool(m.has_glyphs),  # an emoji or icon OCR couldn't spell, as \u25c7 (#128)
    }


def _overlaps(gaps: list, start: float, end: float) -> bool:
    """The rule of the Sessions view (#29): a gap that only touches the match doesn't count."""
    return any(g_start < end and (g_end is None or g_end > start) for g_start, g_end, _ in gaps)


def _write_list(out, key: str, items: Iterable[dict], last: bool = False) -> None:
    """One top-level list, item by item, so a big database never sits in memory at once."""
    out.write(f'  "{key}": [')
    first = True
    for item in items:
        text = json.dumps(item, ensure_ascii=False, indent=2)
        out.write(("\n" if first else ",\n") + textwrap.indent(text, "    "))
        first = False
    out.write("]" if first else "\n  ]")
    out.write("\n" if last else ",\n")


def export_all(
    store: Store, folder: Path, now: float, progress: Callable[[int, int], None] | None = None
) -> Path:
    """Everything as yaptracker-export.json. Reads from its own connection, so capture goes on;
    `progress(done, total)` counts messages."""
    folder.mkdir(parents=True, exist_ok=True)
    path, tmp = folder / "yaptracker-export.json", folder / "yaptracker-export.json.tmp"
    snapshot = store.read_only_copy()
    try:
        total, done = snapshot.stats().messages, 0
        gaps, matches = snapshot.all_gaps(), {}
        for row in snapshot.all_matches():
            matches.setdefault(row[1], []).append(row)

        def sessions():
            nonlocal done
            for session_id, started, ended in snapshot.all_sessions():
                played = []
                for number, row in enumerate(matches.get(session_id, []), start=1):
                    mid, _, m_start, m_end, outcome, map_, mode, source = row
                    said = snapshot.messages(mid)
                    end = m_end or (said[-1].ts if said else m_start)
                    played.append({
                        "id": mid, "number": number, "started_at": iso(m_start),
                        "ended_at": iso(m_end), "outcome": outcome, "map": map_, "mode": mode,
                        "detected_by": source, "incomplete": _overlaps(gaps, m_start, end),
                        "messages": [_message(m) for m in said],
                    })  # fmt: skip
                    done += len(said)
                    if progress:
                        progress(done, total)
                yield {"id": session_id, "started_at": iso(started), "ended_at": iso(ended),
                       "matches": played}  # fmt: skip

        with tmp.open("w", encoding="utf-8", newline="\n") as out:
            out.write("{\n")
            header = {
                "format": "yaptracker-export",
                "format_version": FORMAT_VERSION,
                "exported_at": iso(now),
                "app_version": __version__,
                "anonymized": False,  # names as read (#158 adds the anonymized kind)
            }
            for key, value in header.items():
                out.write(f'  "{key}": {json.dumps(value)},\n')
            _write_list(out, "sessions", sessions())
            _write_list(out, "messages_outside_matches",
                        (_message(m) for m in snapshot.messages_outside_matches()))  # fmt: skip
            _write_list(out, "players", player_records(snapshot))
            gap_records = ({"started_at": iso(a), "ended_at": iso(b), "reason": why}
                           for a, b, why in gaps)  # fmt: skip
            _write_list(out, "capture_gaps", gap_records, last=True)
            out.write("}\n")
        tmp.replace(path)  # never a half-written export
    finally:
        snapshot.close()
    if progress:
        progress(total, total)
    return path
