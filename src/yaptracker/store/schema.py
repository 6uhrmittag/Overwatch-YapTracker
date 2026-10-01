"""Schema migrations, oldest first. Never edit a released one - add a new one instead.

MIGRATIONS[n] takes the database from version n to n + 1.
"""

V1 = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (0);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL
);

CREATE TABLE matches (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    started_at REAL NOT NULL,
    ended_at REAL,
    outcome TEXT,
    map TEXT,
    mode TEXT,
    source TEXT NOT NULL CHECK (source IN ('heroselect', 'endscreen', 'gap', 'hotkey'))
);

CREATE TABLE players (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    verdict TEXT CHECK (verdict IN ('friend', 'fun', 'neutral', 'avoid')),
    notes TEXT NOT NULL DEFAULT '',
    first_seen REAL,
    last_seen REAL
);

CREATE TABLE player_aliases (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    PRIMARY KEY (player_id, alias)
);

CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id),
    ts REAL NOT NULL,
    channel TEXT NOT NULL,
    speaker_raw TEXT,
    player_id INTEGER REFERENCES players(id),
    hero TEXT,
    text TEXT NOT NULL,
    ocr_confidence REAL,
    flagged TEXT CHECK (flagged IN ('overwatch', 'manual'))
);
CREATE INDEX chat_messages_by_match ON chat_messages (match_id, ts);
CREATE INDEX chat_messages_by_player ON chat_messages (player_id);

CREATE TABLE capture_gaps (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    reason TEXT NOT NULL
        CHECK (reason IN ('crash', 'no_frames', 'paused', 'window_lost', 'app_not_running'))
);

-- Full-text search over what was said and who said it, kept in sync by triggers.
CREATE VIRTUAL TABLE chat_fts USING fts5(
    text, speaker_raw, content='chat_messages', content_rowid='id'
);
CREATE TRIGGER chat_fts_insert AFTER INSERT ON chat_messages BEGIN
    INSERT INTO chat_fts (rowid, text, speaker_raw) VALUES (new.id, new.text, new.speaker_raw);
END;
CREATE TRIGGER chat_fts_delete AFTER DELETE ON chat_messages BEGIN
    INSERT INTO chat_fts (chat_fts, rowid, text, speaker_raw)
    VALUES ('delete', old.id, old.text, old.speaker_raw);
END;
CREATE TRIGGER chat_fts_update AFTER UPDATE OF text, speaker_raw ON chat_messages BEGIN
    INSERT INTO chat_fts (chat_fts, rowid, text, speaker_raw)
    VALUES ('delete', old.id, old.text, old.speaker_raw);
    INSERT INTO chat_fts (rowid, text, speaker_raw) VALUES (new.id, new.text, new.speaker_raw);
END;
"""

# Who said it (#74, #18): 'me', 'crew' or NULL, so transcripts, search and export can show it.
V2 = """
ALTER TABLE chat_messages ADD COLUMN role TEXT CHECK (role IN ('me', 'crew'));
"""

# The line had an emoji or icon OCR couldn't spell, marked as ◇ in the text (#128).
V3 = """
ALTER TABLE chat_messages ADD COLUMN has_glyphs INTEGER NOT NULL DEFAULT 0;
"""

MIGRATIONS = [V1, V2, V3]
