"""tools/evidence.py (#437): the waiting issues answered from a data folder (logs, DB, debug)."""

import importlib.util
import time
from pathlib import Path

from yaptracker.store.repo import Store

SCRIPT = Path(__file__).parents[1] / "tools" / "evidence.py"
_spec = importlib.util.spec_from_file_location("evidence", SCRIPT)
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)

T0 = time.mktime((2026, 10, 12, 20, 0, 0, 0, 0, -1))


def stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + ",000"


def data_folder(tmp_path: Path, paused: bool) -> Path:
    data = tmp_path / "data"
    (data / "logs").mkdir(parents=True)
    store = Store.open(data / "yaptracker.db", data / "backups")
    session = store.start_session(T0)
    comp = store.start_match(session, T0 + 60, "heroselect", "COMPETITIVE", "Circuit Royal")
    store.end_match(comp, T0 + 900, "victory")
    store.start_match(session, T0 + 1000, "heroselect", "UNRANKED", "Circuit Royal")
    pid = store.add_player("NoodleBonk", T0)
    store.set_notes(pid, "nice Ana")
    store.close()
    end = time.strftime("%Y-%m-%d/%H-%M-%S", time.localtime(T0 + 900))
    (data / "debug" / f"{end}-end").mkdir(parents=True)
    log = [
        f"{stamp(T0)} INFO yaptracker.system_info: system: YapTracker v0.5.470 | Windows 11",
        f"{stamp(T0 + 61)} INFO yaptracker.reading_mode: reading: after (COMPETITIVE, match 1)",
        f"{stamp(T0 + 62)} INFO yaptracker.capture.wgc: capture: asking Windows for 4 frames a "
        "second (in a match)",
        f"{stamp(T0 + 120)} INFO yaptracker.reader: chat reading: 4 frames, 90 ms CPU each "
        "(after 4); whole app: 20.0 % of a core",
        f"{stamp(T0 + 120)} INFO yaptracker.cpu_parts: cpu threads (in match): native 11.5 %, "
        "capture watcher 8.0 %, chat reader 2.5 %",
        f"{stamp(T0 + 121)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median 120, "
        "p10 110, n=11 — running, in match; 30 ms CPU per read",
        f"{stamp(T0 + 400)} INFO yaptracker.matches: match 1: round 2 (same map, no result yet)",
        f"{stamp(T0 + 410)} INFO yaptracker.reader: chat reading: 2 line(s) seen twice but never "
        "stored: Pip: hi; Bo: yo",
        f"{stamp(T0 + 420)} INFO yaptracker.familiar: familiar face: player #7 (last met "
        "2026-10-09)",
        f"{stamp(T0 + 950)} INFO yaptracker.reader: tidied match 1: 2 fixed, 1 found, 3 removed "
        "(light readings the best reader didn't confirm: repeats, pieces)",
        f"{stamp(T0 + 2000)} INFO yaptracker.evenings: evening 2026-10-12: 2 matches (hero select "
        "2, gap 0, hand 0) · whole app 20 % of a core",
    ]
    if paused:
        log.append(f"{stamp(T0 + 1100)} INFO yaptracker.game_fps: game fps (Overwatch overlay): "
                   "median 124, p10 118, n=11 — paused, in match; 30 ms CPU per read")  # fmt: skip
    (data / "logs" / "yaptracker.log.1").write_text(log[0] + "\n", encoding="utf-8")  # rotated
    (data / "logs" / "yaptracker.log").write_text("\n".join(log[1:]) + "\n", encoding="utf-8")
    return data


def test_the_report_answers_every_waiting_issue_with_ids_only(tmp_path):
    text = evidence.report(data_folder(tmp_path, paused=True))
    assert "whole app avg 20.0 % of a core" in text and "v0.5.470" in text
    assert "native 11.5 %, capture watcher 8.0 %, chat reader 2.5 %" in text
    assert "seen but not stored 2" in text and "capture 4 fps in a match" in text
    assert "after running: 120 fps (n=1)" in text  # per reading mode, with the version
    assert "running 120 fps vs paused 124 fps: costs 3.2 % (within the 5 % bar)" in text
    assert "Competitive matches: 1 (#1 2026-10-12)" in text
    assert "Circuit Royal ×2" in text and "#1 round 2" in text
    assert "of a Competitive match: 2026-10-12/" in text  # the ranked end sample, found
    assert "players with notes: 1" in text and "familiar faces shown: 1" in text
    assert "tidied match 1: 2 fixed, 1 found, 3 removed" in text
    assert "evening 2026-10-12: 2 matches" in text
    for name in ("NoodleBonk", "Pip", "Bo:"):  # ids only, never a name
        assert name not in text, name


def test_no_paused_match_is_said_and_a_missing_db_is_no_crash(tmp_path):
    data = data_folder(tmp_path, paused=False)
    assert "no paused in-match samples (running median 120 fps, n=1)" in evidence.report(data)
    (data / "yaptracker.db").unlink()
    assert "## #34" in evidence.report(data)
