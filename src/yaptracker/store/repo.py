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


@dataclass(frozen=True)
class Stats:
    messages: int
    sessions: int
    matches: int
    players: int


_MESSAGE_COLUMNS = (
    "id, match_id, ts, channel, speaker_raw, player_id, hero, text, ocr_confidence, flagged, role"
)


def _fts_query(text: str) -> str:
    """Every word as a quoted FTS5 phrase, so user input can't break the query syntax."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in text.split())


class Store:
    """Thread-safe: capture writes from its thread while the UI reads (WAL allows both)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    @classmethod
    def open(cls, path: Path | None = None, backups: Path | None = None) -> "Store":
        return cls(connect(path or paths.db_file(), backups or paths.backup_dir()))

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
        self, match_id: int, source: str, mode: str | None, map_name: str | None
    ) -> None:
        """A match started by chat turned out to be a hero-select start (#93)."""
        self._write(
            "UPDATE matches SET source = ?, mode = ?, map = ? WHERE id = ?",
            (source, mode, map_name, match_id),
        )

    def end_match(self, match_id: int, ts: float, outcome: str | None = None) -> None:
        self._write(
            "UPDATE matches SET ended_at = ?, outcome = ? WHERE id = ?", (ts, outcome, match_id)
        )

    def latest_session(self) -> tuple[int, float] | None:
        """(id, last activity) of the newest session: when it ended, or its newest yap/match."""
        rows = self._read(
            "SELECT s.id, MAX(COALESCE(s.ended_at, s.started_at), "
            "COALESCE((SELECT MAX(ts) FROM chat_messages c JOIN matches m ON m.id = c.match_id "
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
        """1 for the first match of its session, 2 for the next..."""
        return self._read(
            "SELECT COUNT(*) FROM matches WHERE id <= ? AND session_id = "
            "(SELECT session_id FROM matches WHERE id = ?)",
            (match_id, match_id),
        )[0][0]

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
    ) -> int:
        return self._write(
            "INSERT INTO chat_messages (match_id, ts, channel, speaker_raw, hero, text, "
            "ocr_confidence, flagged, role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (match_id, ts, channel, speaker_raw, hero, text, ocr_confidence, flagged, role),
        )

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
    ) -> None:
        """A better reading of a stored line (#18); the full-text index follows by trigger."""
        self._write(
            "UPDATE chat_messages SET channel = ?, speaker_raw = ?, hero = ?, text = ?, "
            "ocr_confidence = ?, flagged = ?, role = ? WHERE id = ?",
            (channel, speaker_raw, hero, text, ocr_confidence, flagged, role, message_id),
        )

    def messages(self, match_id: int) -> list[Message]:
        rows = self._read(
            f"SELECT {_MESSAGE_COLUMNS} FROM chat_messages WHERE match_id = ? ORDER BY ts, id",
            (match_id,),
        )
        return [Message(*row) for row in rows]

    def search(self, text: str, limit: int = 50) -> list[Message]:
        """Full-text search over what was said and who said it, best matches first."""
        if not text.strip():
            return []
        columns = ", ".join(f"m.{c.strip()}" for c in _MESSAGE_COLUMNS.split(","))
        rows = self._read(
            f"SELECT {columns} FROM chat_fts JOIN chat_messages m ON m.id = chat_fts.rowid "
            "WHERE chat_fts MATCH ? ORDER BY rank LIMIT ?",
            (_fts_query(text), limit),
        )
        return [Message(*row) for row in rows]

    # Capture gaps (#75) -----------------------------------------------------------------------

    def open_gap(self, ts: float, reason: str) -> int:
        return self._write(
            "INSERT INTO capture_gaps (started_at, reason) VALUES (?, ?)", (ts, reason)
        )

    def close_gap(self, gap_id: int, ts: float) -> None:
        self._write("UPDATE capture_gaps SET ended_at = ? WHERE id = ?", (ts, gap_id))

    # Overview -------------------------------------------------------------------------------

    def stats(self) -> Stats:
        (row,) = self._read(
            "SELECT (SELECT COUNT(*) FROM chat_messages), (SELECT COUNT(*) FROM sessions), "
            "(SELECT COUNT(*) FROM matches), (SELECT COUNT(*) FROM players)"
        )
        return Stats(*row)
