"""One-time clean-ups of lines that were never chat (#422)."""

import time

from yaptracker.cleanups import remove_input_hints_once
from yaptracker.store.repo import Store

T0 = time.mktime((2026, 10, 11, 19, 38, 0, 0, 0, -1))


def test_stored_chat_field_hints_go_once_with_the_player_they_made(tmp_path):
    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        match = store.start_match(store.start_session(T0), T0, "heroselect", "UNRANKED")
        made = store.add_player("Match", T0)  # a player only the hint made
        pip = store.add_player("Pip", T0)
        store.add_message(ts=T0 + 1, channel="unknown", text="PRESS TAB TO CYCLE CHANNELS",
                          speaker_raw="Match", player_id=made, match_id=match)  # fmt: skip
        store.add_message(ts=T0 + 2, channel="match", text="gg", speaker_raw="Pip",
                          player_id=pip, match_id=match)  # fmt: skip
        done = []
        assert remove_input_hints_once(store, tmp_path / "backups", lambda: bool(done),
                                       lambda: done.append(True)) == 1  # fmt: skip
        assert [m.text for m in store.messages(match)] == ["gg"]
        assert [p.display_name for p in store.players()] == ["Pip"]
        assert list((tmp_path / "backups").glob("yaptracker-before-cleanup-*.db"))
        assert remove_input_hints_once(store, tmp_path / "backups", lambda: bool(done),
                                       lambda: done.append(True)) == 0  # once  # fmt: skip
    finally:
        store.close()


def test_lines_stored_without_text_go_once(tmp_path):
    """#424: a callout stored before its message row was read had empty text (30 such lines in
    Marv's data). They go once; a line with only an icon (◇) stays."""
    from yaptracker.cleanups import remove_empty_lines_once

    store = Store.open(tmp_path / "yaptracker.db", tmp_path / "backups")
    try:
        match = store.start_match(store.start_session(T0), T0, "heroselect", "UNRANKED")
        for n, text in enumerate(["", "  ", "gg", "◇"]):
            store.add_message(ts=T0 + n, channel="team", text=text, speaker_raw="Void",
                              hero="Doctrine", match_id=match, has_glyphs=text == "◇")  # fmt: skip
        done = []
        assert remove_empty_lines_once(store, tmp_path / "backups", lambda: bool(done),
                                       lambda: done.append(True)) == 2  # fmt: skip
        assert [m.text for m in store.messages(match)] == ["gg", "◇"]
        assert remove_empty_lines_once(store, tmp_path / "backups", lambda: bool(done),
                                       lambda: done.append(True)) == 0  # fmt: skip
    finally:
        store.close()
