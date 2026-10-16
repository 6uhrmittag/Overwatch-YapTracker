"""Open the database: WAL mode, migrations, and a backup before every migration (#15)."""

import logging
import os
import sqlite3
import time
from pathlib import Path

from yaptracker.store.schema import MIGRATIONS

log = logging.getLogger(__name__)
LATEST = len(MIGRATIONS)


class NewerDatabaseError(RuntimeError):
    """The database was written by a newer YapTracker. Never touch it: update the app instead."""


def version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    return conn.execute("SELECT version FROM schema_version").fetchone()[0] if exists else 0


def copy_to(conn: sqlite3.Connection, target: Path) -> None:
    """A consistent copy via SQLite's backup API (safe even while WAL has unmerged pages), into
    <target>.part first (#461): a copy that fails halfway (full disk, crash) never sits under a
    backup's name, nor replaces a good one. A .part left by an earlier failure goes first."""
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    try:
        copy = sqlite3.connect(part)
        try:
            conn.backup(copy)
        finally:
            copy.close()
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def backup(conn: sqlite3.Connection, backups: Path, from_version: int) -> Path:
    """The copy before a schema migration."""
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"yaptracker-v{from_version}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    copy_to(conn, target)
    return target


def connect(path: Path, backups: Path) -> sqlite3.Connection:
    """Open (or create) the database and bring it to the latest schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    # WAL + NORMAL: crash-safe, and no fsync per yap (a power cut can lose the last few seconds).
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    current = version(conn)
    if current > LATEST:
        conn.close()
        raise NewerDatabaseError(
            f"{path} has schema v{current}, this YapTracker only knows v{LATEST}. Update the app."
        )
    if 0 < current < LATEST:
        log.info("database backed up to %s before migrating", backup(conn, backups, current))
    for step in range(current, LATEST):
        conn.executescript(
            "BEGIN;\n"
            + MIGRATIONS[step]
            + f"\nUPDATE schema_version SET version = {step + 1};\nCOMMIT;"
        )
        log.info("database migrated to schema v%d", step + 1)
    return conn
