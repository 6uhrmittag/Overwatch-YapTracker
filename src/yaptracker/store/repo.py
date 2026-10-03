"""The repository: the only place that reads or writes the database. The UI calls these methods."""

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from yaptracker import paths
from yaptracker.store.db import connect


@dataclass(frozen=True)
class Message:
    id: int
    match_id: int | None
    ts: float
    channel: str
    speaker_raw: str | None
    player_id: int | None
    hero: str | None
    text: str
    ocr_confidence: float | None
    flagged: str | None
    role: str | None = None  # 'me' / 'crew' (#74)
    has_glyphs: int = 0  # an emoji or icon, shown as ◇ (#128)
    edited_at: float | None = None  # fixed by hand (#227); the OCR reading is in original_text
    original_text: str | None = None


@dataclass(frozen=True)
class PlayerRow:
    """A yapper in the Yappers list (#24)."""

    id: int
    display_name: str
    verdict: str | None
    notes: str
    first_seen: float | None
    last_seen: float | None
    matches: int
    yaps: int
    spicy: int = 0  # flagged lines: [Report] by Overwatch or marked by you (#77)
    callouts: int = 0  # comms-wheel lines ("Enemy Sombra!"): not counted as yaps (#182)


@dataclass(frozen=True)
class SessionRow:
    """An evening in the Sessions list (#29)."""

    id: int
    started_at: float
    ended_at: float  # its end, or its last yap/match if YapTracker never saw the end
    matches: int
    yaps: int


@dataclass(frozen=True)
class MatchRow:
    """A match in a session (#29)."""

    id: int
    started_at: float
    ended_at: float | None
    outcome: str | None
    map: str | None
    mode: str | None
    yaps: int
    last_yap: float | None


@dataclass(frozen=True)
class Hit:
    """A search result (#30): the line, where it was said, and its text with the found words
    between \x01 and \x02 (the view turns them into highlights)."""

    message: Message
    marked: str
    session_id: int | None
    match_number: int | None
    map: str | None


@dataclass(frozen=True)
class Stats:
    messages: int
    sessions: int
    matches: int
    players: int


_MESSAGE_COLUMNS = (
    "id, match_id, ts, channel, speaker_raw, player_id, hero, text, ocr_confidence, flagged, role, "
    "has_glyphs, edited_at, original_text"
)


def _fts_query(text: str) -> str:
    """Every word as a quoted FTS5 phrase, so user input can't break the query syntax."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in text.split())


def _fts_prefixes(text: str) -> str:
    """Like _fts_query, but every word also finds longer ones: "rein" finds "reinhardt"."""
    return " ".join(f"{word}*" for word in _fts_query(text).split())


def _played(m: str) -> str:
    """SQL: match `m` was played - it has a line or a result (#270). A match with neither
    (a press of New match before #269, a lobby that never chatted) is hidden everywhere."""
    return (f"(EXISTS (SELECT 1 FROM live_messages pl WHERE pl.match_id = {m}.id) "
            f"OR {m}.outcome IS NOT NULL)")  # fmt: skip


class Store:
    """Thread-safe: capture writes from its thread while the UI reads (WAL allows both)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path | None = None, backups: Path | None = None) -> "Store":
        return cls(connect(path or paths.db_file(), backups or paths.backup_dir()))

    def read_only_copy(self) -> "Store":
        """A second Store on its own read-only connection, for long reads like the export (#69):
        capture keeps writing meanwhile (WAL), nobody waits for the other's lock."""
        path = next(row[2] for row in self._read("PRAGMA database_list") if row[1] == "main")
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True,
                               check_same_thread=False)  # fmt: skip
        return Store(conn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def backup_to(self, target: Path) -> None:
        """A consistent copy of the whole database, safe while the app runs (#125)."""
        with self._lock, sqlite3.connect(target) as copy:
            self._conn.backup(copy)
        copy.close()

    def _write(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, params).lastrowid

    def _read(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # Sessions and matches -------------------------------------------------------------------

    def start_session(self, ts: float) -> int:
        return self._write("INSERT INTO sessions (started_at) VALUES (?)", (ts,))

    def end_session(self, session_id: int, ts: float) -> None:
        self._write("UPDATE sessions SET ended_at = ? WHERE id = ?", (ts, session_id))

    def start_match(
        self,
        session_id: int,
        ts: float,
        source: str,
        mode: str | None = None,
        map_name: str | None = None,
    ) -> int:
        return self._write(
            "INSERT INTO matches (session_id, started_at, source, mode, map) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, ts, source, mode, map_name),
        )

    def set_match_source(
        self,
        match_id: int,
        source: str,
        mode: str | None,
        map_name: str | None,
        started_at: float | None = None,
    ) -> None:
        """A match started by chat turned out to be a hero-select start (#93). A start by
        hand also hands over its start time (#269)."""
        self._write(
            "UPDATE matches SET source = ?, mode = ?, map = ?, "
            "started_at = COALESCE(?, started_at) WHERE id = ?",
            (source, mode, map_name, started_at, match_id),
        )

    def drop_match(self, match_id: int) -> bool:
        """Remove a match that never got a line (#269: a start by hand nothing happened in).
        One statement, so a line arriving meanwhile keeps it. True when it was removed."""
        with self._lock:
            return bool(
                self._conn.execute(
                    "DELETE FROM matches WHERE id = ? AND NOT EXISTS "
                    "(SELECT 1 FROM chat_messages WHERE match_id = ?)",
                    (match_id, match_id),
                ).rowcount
            )

    def end_match(self, match_id: int, ts: float, outcome: str | None = None) -> None:
        self._write(
            "UPDATE matches SET ended_at = ?, outcome = ? WHERE id = ?", (ts, outcome, match_id)
        )

    def latest_session(self) -> tuple[int, float] | None:
        """(id, last activity) of the newest session: when it ended, or its newest yap/match."""
        rows = self._read(
            "SELECT s.id, MAX(COALESCE(s.ended_at, s.started_at), "
            "COALESCE((SELECT MAX(ts) FROM live_messages c JOIN matches m ON m.id = c.match_id "
            "WHERE m.session_id = s.id), 0), "
            "COALESCE((SELECT MAX(started_at) FROM matches WHERE session_id = s.id), 0)) "
            "FROM sessions s ORDER BY s.id DESC LIMIT 1"
        )
        return (rows[0][0], rows[0][1]) if rows else None

    def reopen_session(self, session_id: int) -> None:
        self._write("UPDATE sessions SET ended_at = NULL WHERE id = ?", (session_id,))

    def session_number(self, session_id: int) -> int:
        """1 for the first session ever, 2 for the next... (ids can have holes)."""
        return self._read("SELECT COUNT(*) FROM sessions WHERE id <= ?", (session_id,))[0][0]

    def match_number(self, match_id: int) -> int:
        """1 for the first match of its session, 2 for the next... Empty ones don't count."""
        return self._read(
            "SELECT COUNT(*) FROM matches m WHERE m.id <= ? AND m.session_id = "
            f"(SELECT session_id FROM matches WHERE id = ?) AND (m.id = ? OR {_played('m')})",
            (match_id, match_id, match_id),
        )[0][0]

    def sessions(self) -> list[SessionRow]:
        """Every session with at least one match, newest first (#29)."""
        rows = self._read(
            "SELECT s.id, s.started_at, COALESCE(s.ended_at, MAX(s.started_at, "
            "COALESCE((SELECT MAX(c.ts) FROM live_messages c JOIN matches m ON m.id = c.match_id "
            "WHERE m.session_id = s.id), 0), "
            "COALESCE((SELECT MAX(COALESCE(ended_at, started_at)) FROM matches "
            "WHERE session_id = s.id), 0))), "
            f"(SELECT COUNT(*) FROM matches p WHERE p.session_id = s.id AND {_played('p')}) AS n, "
            "(SELECT COUNT(*) FROM live_messages c JOIN matches m ON m.id = c.match_id "
            "WHERE m.session_id = s.id) "
            "FROM sessions s WHERE n > 0 ORDER BY s.started_at DESC, s.id DESC"
        )
        return [SessionRow(*row) for row in rows]

    def session_matches(self, session_id: int) -> list[MatchRow]:
        """The matches of a session in play order, with how much was said (#29)."""
        rows = self._read(
            "SELECT m.id, m.started_at, m.ended_at, m.outcome, m.map, m.mode, COUNT(c.id), "
            "MAX(c.ts) FROM matches m LEFT JOIN live_messages c ON c.match_id = m.id "
            "WHERE m.session_id = ? GROUP BY m.id "
            "HAVING COUNT(c.id) > 0 OR m.outcome IS NOT NULL ORDER BY m.started_at, m.id",
            (session_id,),
        )
        return [MatchRow(*row) for row in rows]

    # Players (#23) ---------------------------------------------------------------------------

    def add_player(self, display_name: str, ts: float) -> int:
        return self._write(
            "INSERT INTO players (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
            (display_name, ts, ts),
        )

    def add_alias(self, player_id: int, alias: str) -> None:
        self._write(
            "INSERT OR IGNORE INTO player_aliases (player_id, alias) VALUES (?, ?)",
            (player_id, alias),
        )

    def rename_player(self, player_id: int, display_name: str) -> None:
        self._write("UPDATE players SET display_name = ? WHERE id = ?", (display_name, player_id))

    def player_seen(self, player_id: int, ts: float) -> None:
        self._write(
            "UPDATE players SET last_seen = MAX(COALESCE(last_seen, ?), ?) WHERE id = ?",
            (ts, ts, player_id),
        )

    def players(self) -> list[PlayerRow]:
        """Every player with how often you met them and how much they said."""
        rows = self._read(
            "SELECT p.id, p.display_name, p.verdict, p.notes, p.first_seen, p.last_seen, "
            # yaps are typed lines; comms-wheel callouts (the lines with a hero) apart (#182)
            "COUNT(DISTINCT c.match_id), COUNT(c.id) - COUNT(c.hero), COUNT(c.flagged), "
            "COUNT(c.hero) "
            "FROM players p LEFT JOIN live_messages c ON c.player_id = p.id GROUP BY p.id"
        )
        return [PlayerRow(*row) for row in rows]

    def player(self, player_id: int) -> PlayerRow | None:
        found = [p for p in self.players() if p.id == player_id]
        return found[0] if found else None

    def aliases(self, player_id: int) -> list[str]:
        rows = self._read(
            "SELECT alias FROM player_aliases WHERE player_id = ? ORDER BY alias", (player_id,)
        )
        return [alias for (alias,) in rows]

    def player_messages(self, player_id: int, callouts: bool = False) -> list[Message]:
        """What they typed, newest first (the profile groups it by match, #25); with
        `callouts`, their comms-wheel lines too (#182)."""
        typed = "" if callouts else " AND hero IS NULL"
        rows = self._read(
            f"SELECT {_MESSAGE_COLUMNS} FROM live_messages WHERE player_id = ?{typed} "
            "ORDER BY ts DESC, id DESC",
            (player_id,),
        )
        return [Message(*row) for row in rows]

    def player_heroes(self, player_id: int) -> list[str]:
        """The heroes their callouts named, most used first ("Seen as Kiriko, Lucio", #182)."""
        rows = self._read(
            "SELECT hero FROM live_messages WHERE player_id = ? AND hero IS NOT NULL "
            "GROUP BY hero ORDER BY COUNT(*) DESC, hero",
            (player_id,),
        )
        return [hero for (hero,) in rows]

    def met_before(
        self, player_id: int, match_id: int | None
    ) -> tuple[int, int, float | None, int]:
        """(matches, yaps, last time, spicy yaps) with this player before the given match.
        Callouts count for the matches (they were there), not as yaps (#182)."""
        (row,) = self._read(
            "SELECT COUNT(DISTINCT match_id), COUNT(*) - COUNT(hero), MAX(ts), COUNT(flagged) "
            "FROM live_messages WHERE player_id = ? AND match_id IS NOT ?",
            (player_id, match_id),
        )
        return row

    def edit_message(self, message_id: int, text: str, ts: float) -> None:
        """Fixed by hand (#227): the first OCR reading is kept, search follows the new text."""
        self._write(
            "UPDATE chat_messages SET original_text = COALESCE(original_text, text), text = ?, "
            "edited_at = ? WHERE id = ?",
            (text, ts, message_id),
        )

    def unedit_message(self, message_id: int, text: str, edited_at: float | None) -> None:
        """Undo an edit: the text and mark as they were before."""
        self._write(
            "UPDATE chat_messages SET text = ?, edited_at = ?, "
            "original_text = CASE WHEN ? IS NULL THEN NULL ELSE original_text END WHERE id = ?",
            (text, edited_at, edited_at, message_id),
        )

    def delete_message(self, message_id: int, ts: float) -> None:
        """Hidden everywhere from now on, kept in the table (#227)."""
        self._write("UPDATE chat_messages SET deleted_at = ? WHERE id = ?", (ts, message_id))

    def restore_message(self, message_id: int) -> None:
        """Undo a delete."""
        self._write("UPDATE chat_messages SET deleted_at = NULL WHERE id = ?", (message_id,))

    def set_flag(self, message_id: int, flagged: str | None) -> None:
        """Mark a line as spicy ('manual') or take it back (None) (#77)."""
        self._write("UPDATE chat_messages SET flagged = ? WHERE id = ?", (flagged, message_id))

    def set_notes(self, player_id: int, notes: str) -> None:
        self._write("UPDATE players SET notes = ? WHERE id = ?", (notes, player_id))

    def match_started(self, match_id: int) -> float | None:
        rows = self._read("SELECT started_at FROM matches WHERE id = ?", (match_id,))
        return rows[0][0] if rows else None

    def merge_players(self, source_id: int, target_id: int) -> None:
        """OCR made two players of one person (#28): source goes into target, nothing is lost.

        Their lines move over, notes are joined, source's names become target's aliases, a
        missing verdict is taken over, first/last met combined. One transaction.
        """
        with self._lock:
            conn = self._conn
            source = conn.execute(
                "SELECT display_name, verdict, notes, first_seen, last_seen FROM players "
                "WHERE id = ?", (source_id,)
            ).fetchone()  # fmt: skip
            target = conn.execute(
                "SELECT verdict, notes, first_seen, last_seen FROM players WHERE id = ?",
                (target_id,),
            ).fetchone()
            if source is None or target is None or source_id == target_id:
                return
            name, verdict, notes, first, last = source
            joined = "\n\n".join(n.strip() for n in (target[1], notes) if n and n.strip())
            firsts = [t for t in (target[2], first) if t is not None]
            lasts = [t for t in (target[3], last) if t is not None]
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "UPDATE chat_messages SET player_id = ? WHERE player_id = ?",
                    (target_id, source_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO player_aliases (player_id, alias) "
                    "SELECT ?, alias FROM player_aliases WHERE player_id = ? UNION SELECT ?, ?",
                    (target_id, source_id, target_id, name),
                )
                conn.execute(
                    "UPDATE players SET notes = ?, verdict = COALESCE(verdict, ?), "
                    "first_seen = ?, last_seen = ? WHERE id = ?",
                    (joined, verdict, min(firsts, default=None), max(lasts, default=None),
                     target_id),
                )  # fmt: skip
                conn.execute("DELETE FROM players WHERE id = ?", (source_id,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def set_verdict(self, player_id: int, verdict: str | None) -> None:
        self._write("UPDATE players SET verdict = ? WHERE id = ?", (verdict, player_id))

    def player_names(self) -> list[tuple[int, str]]:
        """(player id, name) for every display name and alias: what a speaker is matched to."""
        return self._read(
            "SELECT id, display_name FROM players UNION SELECT player_id, alias FROM player_aliases"
        )

    # Chat -----------------------------------------------------------------------------------

    def add_message(
        self,
        *,
        ts: float,
        channel: str,
        text: str,
        speaker_raw: str | None = None,
        match_id: int | None = None,
        hero: str | None = None,
        ocr_confidence: float | None = None,
        flagged: str | None = None,
        role: str | None = None,
        has_glyphs: bool = False,
        player_id: int | None = None,
    ) -> int:
        return self._write(
            "INSERT INTO chat_messages (match_id, ts, channel, speaker_raw, hero, text, "
            "ocr_confidence, flagged, role, has_glyphs, player_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (match_id, ts, channel, speaker_raw, hero, text, ocr_confidence, flagged, role,
             int(has_glyphs), player_id),
        )  # fmt: skip

    def update_message(
        self,
        message_id: int,
        *,
        channel: str,
        text: str,
        speaker_raw: str | None = None,
        hero: str | None = None,
        ocr_confidence: float | None = None,
        flagged: str | None = None,
        role: str | None = None,
        has_glyphs: bool = False,
        player_id: int | None = None,
    ) -> None:
        """A better reading of a stored line (#18); the full-text index follows by trigger.
        A line fixed by hand keeps its text (#227)."""
        self._write(
            "UPDATE chat_messages SET channel = ?, speaker_raw = ?, hero = ?, "
            "text = CASE WHEN edited_at IS NULL THEN ? ELSE text END, "
            "ocr_confidence = ?, flagged = ?, role = ?, has_glyphs = ?, player_id = ? "
            "WHERE id = ?",
            (channel, speaker_raw, hero, text, ocr_confidence, flagged, role, int(has_glyphs),
             player_id, message_id),
        )  # fmt: skip

    def message(self, message_id: int) -> Message | None:
        rows = self._read(f"SELECT {_MESSAGE_COLUMNS} FROM chat_messages WHERE id = ?",
                          (message_id,))  # fmt: skip
        return Message(*rows[0]) if rows else None

    def messages(self, match_id: int) -> list[Message]:
        rows = self._read(
            f"SELECT {_MESSAGE_COLUMNS} FROM live_messages WHERE match_id = ? ORDER BY ts, id",
            (match_id,),
        )
        return [Message(*row) for row in rows]

    def search(self, text: str, limit: int = 50) -> list[Message]:
        """Full-text search over what was said and who said it, best matches first."""
        if not text.strip():
            return []
        columns = ", ".join(f"m.{c.strip()}" for c in _MESSAGE_COLUMNS.split(","))
        rows = self._read(
            f"SELECT {columns} FROM chat_fts JOIN live_messages m ON m.id = chat_fts.rowid "
            "WHERE chat_fts MATCH ? ORDER BY rank LIMIT ?",
            (_fts_query(text), limit),
        )
        return [Message(*row) for row in rows]

    def find(
        self,
        text: str,
        *,
        channel: str | None = None,
        player_ids: list[int] | None = None,
        since: float | None = None,
        callouts: bool = False,
        limit: int = 100,
    ) -> list[Hit]:
        """Search all chat (#30), newest first. Words match what was said and who said it, also
        as the start of a longer word; empty text with a filter lists everything it lets through.
        Typed lines only, unless `callouts` (comms-wheel lines, #182)."""
        where, params = [], []
        if channel:
            where.append("m.channel = ?")
            params.append(channel)
        if player_ids is not None:
            where.append(f"m.player_id IN ({', '.join('?' * len(player_ids))})")
            params.extend(player_ids)
        if since is not None:
            where.append("m.ts >= ?")
            params.append(since)
        columns = ", ".join(f"m.{c.strip()}" for c in _MESSAGE_COLUMNS.split(","))
        place = "mt.session_id, mt.id, mt.map"  # mt.id becomes its number below (#270)
        if text.strip():
            source = "chat_fts JOIN live_messages m ON m.id = chat_fts.rowid"
            marked = "highlight(chat_fts, 0, char(1), char(2))"
            where.insert(0, "chat_fts MATCH ?")
            params.insert(0, _fts_prefixes(text))
        elif where:
            source, marked = "live_messages m", "m.text"
        else:
            return []
        if not callouts:
            where.append("m.hero IS NULL")
        rows = self._read(
            f"SELECT {columns}, {marked}, {place} FROM {source} "
            f"LEFT JOIN matches mt ON mt.id = m.match_id WHERE {' AND '.join(where)} "
            "ORDER BY m.ts DESC, m.id DESC LIMIT ?",
            (*params, limit),
        )
        n = len(_MESSAGE_COLUMNS.split(","))
        numbers = self._match_numbers({row[n + 1] for row in rows} - {None})
        return [Hit(Message(*row[:n]), row[n], row[n + 1], numbers.get(row[n + 2]), row[n + 3])
                for row in rows]  # fmt: skip

    def _match_numbers(self, sessions: set[int]) -> dict[int, int]:
        """{match id: its number in its session} for those sessions, empty matches not counted
        (#270). Once per search instead of a count per hit."""
        if not sessions:
            return {}
        rows = self._read(
            f"SELECT m.id, m.session_id FROM matches m WHERE m.session_id IN "
            f"({', '.join('?' * len(sessions))}) AND {_played('m')} ORDER BY m.session_id, m.id",
            tuple(sessions),
        )
        numbers: dict[int, int] = {}
        counts: dict[int, int] = {}
        for match_id, session_id in rows:
            counts[session_id] = counts.get(session_id, 0) + 1
            numbers[match_id] = counts[session_id]
        return numbers

    # Export (#69) -------------------------------------------------------------------------------

    def all_sessions(self) -> list[tuple[int, float, float | None]]:
        return self._read("SELECT id, started_at, ended_at FROM sessions ORDER BY id")

    def all_matches(self) -> list[tuple]:
        """(id, session_id, started, ended, outcome, map, mode, source) in play order."""
        return self._read(
            "SELECT id, session_id, started_at, ended_at, outcome, map, mode, source "
            f"FROM matches m WHERE {_played('m')} ORDER BY session_id, started_at, id"
        )

    def messages_outside_matches(self) -> list[Message]:
        rows = self._read(
            f"SELECT {_MESSAGE_COLUMNS} FROM live_messages WHERE match_id IS NULL ORDER BY ts, id"
        )
        return [Message(*row) for row in rows]

    def all_gaps(self) -> list[tuple[float, float | None, str]]:
        return self._read("SELECT started_at, ended_at, reason FROM capture_gaps ORDER BY id")

    # Capture gaps (#75) -----------------------------------------------------------------------

    def open_gap(self, ts: float, reason: str) -> int:
        return self._write(
            "INSERT INTO capture_gaps (started_at, reason) VALUES (?, ?)", (ts, reason)
        )

    def close_gap(self, gap_id: int, ts: float) -> None:
        self._write("UPDATE capture_gaps SET ended_at = ? WHERE id = ?", (ts, gap_id))

    def gaps_between(self, start: float, end: float) -> list[tuple[float, float | None, str]]:
        """(started, ended, reason) of every gap overlapping (start, end); None = still open.
        Touching doesn't count: a pause that ends as the next match starts left no hole in it."""
        return self._read(
            "SELECT started_at, ended_at, reason FROM capture_gaps "
            "WHERE started_at < ? AND (ended_at IS NULL OR ended_at > ?) ORDER BY started_at, id",
            (end, start),
        )

    # Overview -------------------------------------------------------------------------------

    def stats(self) -> Stats:
        (row,) = self._read(
            "SELECT (SELECT COUNT(*) FROM live_messages), (SELECT COUNT(*) FROM sessions), "
            f"(SELECT COUNT(*) FROM matches m WHERE {_played('m')}), (SELECT COUNT(*) FROM players)"
        )
        return Stats(*row)
