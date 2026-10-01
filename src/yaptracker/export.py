"""Your data leaves the app: yappers as Markdown and JSON (#31), everything as JSON (#69).

Open formats on purpose: players.md reads well in any notes app, the JSON files are for scripts.
The full export puts the same player records next to sessions, matches, messages and gaps; its
format is documented in docs/export-format.md and docs/export.schema.json.
"""

import json
import re
import secrets
import shutil
import textwrap
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from yaptracker import __version__
from yaptracker.lines import LinePictures
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
            "messages": p.yaps,  # typed lines
            "callouts": p.callouts,  # comms-wheel lines (#182)
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


def _overlapping(gaps: list, start: float, end: float) -> list:
    """The rule of the Sessions view (#29): a gap that only touches the match doesn't count."""
    return [g for g in gaps if g[0] < end and (g[1] is None or g[1] > start)]


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


class _Names:
    """Anonymize names (#158): every yapper and speaker gets a pseudonym like Player-7f3a, the
    same in every file of this export. Random per export, so nobody can hash a name back."""

    def __init__(self, on: bool, players: list[dict]) -> None:
        self.on, self._pseudonyms, self._used = on, {}, set()
        self._player_of: dict[str, int] = {}  # every spelling of a yapper -> their id
        for p in players:
            for name in [p["display_name"], *p["aliases"]]:
                self._player_of.setdefault(name.casefold(), p["id"])

    def of(self, player_id: int | None, name: str | None) -> str | None:
        if not self.on or name is None:
            return name
        player_id = player_id if player_id is not None else self._player_of.get(name.casefold())
        key = ("player", player_id) if player_id is not None else ("name", name.casefold())
        if key not in self._pseudonyms:
            size = 2 if len(self._used) < 20_000 else 3
            while (pseudonym := f"Player-{secrets.token_hex(size)}") in self._used:
                pass
            self._used.add(pseudonym)
            self._pseudonyms[key] = pseudonym
        return self._pseudonyms[key]

    def messages(self, said: list) -> list[dict]:
        """A match's lines; with anonymizing on, names in the text go too ("gg NoodleBonk"):
        every name read in this match, as whole words."""
        records = [_message(m) for m in said]
        if not self.on:
            return records
        names = {
            m.speaker_raw.casefold(): self.of(m.player_id, m.speaker_raw)
            for m in said
            if m.speaker_raw
        }
        found = re.compile(
            r"(?<!\w)("
            + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
            + r")(?!\w)",
            re.IGNORECASE,
        )
        for record in records:
            record["speaker"] = names.get((record["speaker"] or "").casefold())
            if names:
                record["text"] = found.sub(lambda m: names[m.group(1).casefold()], record["text"])
        return records


def _md(text: str) -> str:
    """Chat text as literal Markdown: no accidental bold, links, headings or HTML."""
    return re.sub(r"([\\`*_\[\]<>#|~])", r"\\\1", text)


def _clock(when: str | None) -> str:
    return when[11:16] if when else "?"


_CHANNEL_NAMES = {"team": "Team", "match": "Match", "group": "Group", "system": "System"}
_OUTCOME_WORDS = {"victory": "won", "defeat": "lost", "draw": "draw"}
_GAP_WORDS = {
    "crash": "capture stopped",
    "no_frames": "no picture from Overwatch",
    "window_lost": "lost the Overwatch window",
    "paused": "paused",
    "app_not_running": "YapTracker wasn't running",
}


def session_markdown(session: dict, gaps: dict[int, list]) -> str:
    """One evening as Markdown: a section per match, its chat, and where nothing was recorded
    (`gaps`: match id -> the capture gaps overlapping it)."""
    day = datetime.fromisoformat(session["started_at"]).strftime("%A, %b %d, %Y").replace(" 0", " ")
    yaps = sum(len(m["messages"]) for m in session["matches"])
    span = (
        f"{_clock(session['started_at'])}\u2013{_clock(session['ended_at'])}"
        if session["ended_at"]
        else f"from {_clock(session['started_at'])}"
    )
    counted = f"{_count(len(session['matches']), 'match')} \u00b7 {_count(yaps, 'yap')}"
    out = [f"# {day}\n", f"{span} \u00b7 {counted}\n"]
    for match in session["matches"]:
        title = f"Match {match['number']}" + (f" on {match['map'].title()}" if match["map"] else "")
        extra = [
            w for w in ((match["mode"] or "").title(), _OUTCOME_WORDS.get(match["outcome"])) if w
        ]
        out.append(f"## {' \u00b7 '.join([_md(title), *extra])}\n")
        rows = [(datetime.fromisoformat(m["time"]).timestamp(), 1, m) for m in match["messages"]]
        rows += [(gap[0], 0, gap) for gap in gaps.get(match["id"], [])]
        lines = []
        for _, kind, item in sorted(rows, key=lambda r: (r[0], r[1])):
            if kind == 0:
                a, b, why = item
                until = _clock(iso(b)) if b else "the end"
                lines.append(
                    f"- *Not recorded {_clock(iso(a))}\u2013{until} ({_GAP_WORDS.get(why, why)})*"
                )
                continue
            who = item["speaker"] if item["channel"] != "system" else None
            who = "you" if who and item["role"] == "me" else who
            name = f"**{_md(who)}:** " if who else ""
            channel = _CHANNEL_NAMES.get(item["channel"], "Chat")
            lines.append(
                f"- {_clock(item['time'])} \u00b7 {channel} \u00b7 {name}{_md(item['text'])}"
            )
        out.append("\n".join(lines or ["Nobody typed in this match."]) + "\n")
    return "\n".join(out)


def _readme(
    counts: dict, first: str | None, last: str | None, anonymized: bool, pictures: bool, now: float
) -> str:
    files = [
        "- `yaptracker-export.json`: everything, for scripts. The format is described at "
        "https://github.com/6uhrmittag/Overwatch-YapTracker/blob/main/docs/export-format.md",
        "- `sessions/`: one file per evening, with every match's chat",
        "- `players.md`: your yappers" + (" (without your notes)" if anonymized else ""),
    ]
    if pictures:
        files.append("- `line-images/`: how each line looked in Overwatch, named by message id")
    span = f"From {first[:10]} to {last[:10]}" if first and last else "Nothing recorded yet"
    names = (
        "Names are replaced by Player-xxxx (the same in every file); your notes are left out."
        if anonymized
        else "Names are as read from chat: think before you share this."
    )
    return "\n".join(
        [
            "# YapTracker export\n",
            f"Exported {datetime.fromtimestamp(now):%Y-%m-%d %H:%M} by YapTracker {__version__}.\n",
            f"- {_count(counts['sessions'], 'session')}, {_count(counts['matches'], 'match')}, "
            f"{_count(counts['yaps'], 'yap')}, {_count(counts['players'], 'yapper')}",
            f"- {span}",
            f"- {names}\n",
            "## What's inside\n",
            *files,
            "\nYour data is yours. The format is free to use (MIT).\n",
        ]
    )


def export_all(
    store: Store,
    folder: Path,
    now: float,
    progress: Callable[[int, int], None] | None = None,
    *,
    markdown: bool = False,
    anonymize: bool = False,
    pictures: LinePictures | None = None,
) -> Path:
    """Everything as yaptracker-export.json, optionally with Markdown (README.md, sessions/,
    players.md), anonymized names and the line pictures (never together with anonymizing: the
    pictures show the names). Reads from its own connection, so capture goes on;
    `progress(done, total)` counts messages."""
    folder.mkdir(parents=True, exist_ok=True)
    path, tmp = folder / "yaptracker-export.json", folder / "yaptracker-export.json.tmp"
    pictures = None if anonymize else pictures
    snapshot = store.read_only_copy()
    try:
        total, done = snapshot.stats().messages, 0
        gaps, matches, gaps_of = snapshot.all_gaps(), {}, {}
        for row in snapshot.all_matches():
            matches.setdefault(row[1], []).append(row)
        players = player_records(snapshot)
        names = _Names(anonymize, players)
        counts = {"sessions": 0, "matches": 0, "yaps": 0, "players": len(players)}
        span: list[str | None] = [None, None]

        def picture(record: dict, ts: float) -> dict:
            source = pictures.path(record["id"], ts) if pictures else None
            if source is not None and source.exists():
                target = folder / "line-images" / f"{record['id']}.webp"
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
                record["picture"] = f"line-images/{target.name}"
            return record

        def sessions():
            nonlocal done
            for session_id, started, ended in snapshot.all_sessions():
                played = []
                for number, row in enumerate(matches.get(session_id, []), start=1):
                    mid, _, m_start, m_end, outcome, map_, mode, source = row
                    said = snapshot.messages(mid)
                    end = m_end or (said[-1].ts if said else m_start)
                    gaps_of[mid] = _overlapping(gaps, m_start, end)
                    records = [
                        picture(r, m.ts) for r, m in zip(names.messages(said), said, strict=True)
                    ]
                    played.append(
                        {
                            "id": mid,
                            "number": number,
                            "started_at": iso(m_start),
                            "ended_at": iso(m_end),
                            "outcome": outcome,
                            "map": map_,
                            "mode": mode,
                            "detected_by": source,
                            "incomplete": bool(gaps_of[mid]),
                            "messages": records,
                        }
                    )
                    done += len(said)
                    if progress:
                        progress(done, total)
                session = {
                    "id": session_id,
                    "started_at": iso(started),
                    "ended_at": iso(ended),
                    "matches": played,
                }
                counts["sessions"] += 1
                counts["matches"] += len(played)
                counts["yaps"] += sum(len(m["messages"]) for m in played)
                span[0] = span[0] or session["started_at"]
                span[1] = session["ended_at"] or session["started_at"]
                if markdown:
                    (folder / "sessions").mkdir(exist_ok=True)
                    name = f"{session['started_at'][:10]}-session-{session_id}.md"
                    (folder / "sessions" / name).write_text(
                        session_markdown(session, gaps_of), encoding="utf-8", newline="\n"
                    )
                yield session

        if anonymize:
            players = [
                {
                    **p,
                    "display_name": names.of(p["id"], p["display_name"]),
                    "notes": "",
                    "aliases": [],
                }
                for p in players
            ]
        with tmp.open("w", encoding="utf-8", newline="\n") as out:
            out.write("{\n")
            header = {
                "format": "yaptracker-export",
                "format_version": FORMAT_VERSION,
                "exported_at": iso(now),
                "app_version": __version__,
                "anonymized": anonymize,
            }
            for key, value in header.items():
                out.write(f'  "{key}": {json.dumps(value)},\n')
            _write_list(out, "sessions", sessions())
            outside = snapshot.messages_outside_matches()
            _write_list(out, "messages_outside_matches", names.messages(outside))
            _write_list(out, "players", players)
            gap_records = (
                {"started_at": iso(a), "ended_at": iso(b), "reason": why} for a, b, why in gaps
            )
            _write_list(out, "capture_gaps", gap_records, last=True)
            out.write("}\n")
        tmp.replace(path)  # never a half-written export
        if markdown:
            (folder / "players.md").write_text(
                players_markdown(players, now), encoding="utf-8", newline="\n"
            )
            (folder / "README.md").write_text(
                _readme(counts, *span, anonymize, pictures is not None, now),
                encoding="utf-8",
                newline="\n",
            )
    finally:
        snapshot.close()
    if progress:
        progress(total, total)
    return path
