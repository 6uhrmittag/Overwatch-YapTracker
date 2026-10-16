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
    german = store.start_match(session, T0 + 1000, "heroselect", "GEWERTET", "Circuit Royal")
    store.add_message(ts=T0 + 1100, channel="match", text="gg", match_id=german)
    store.end_match(german, T0 + 1500, "defeat")
    quick = store.start_match(session, T0 + 1600, "heroselect", "UNRANKED", "Circuit Royal")
    store.add_message(ts=T0 + 1700, channel="match", text="hi", match_id=quick)
    pid = store.add_player("NoodleBonk", T0)
    store.set_notes(pid, "nice Ana")
    store.close()
    end = time.strftime("%Y-%m-%d/%H-%M-%S", time.localtime(T0 + 902))  # saved a moment later
    (data / "debug" / f"{end}-end").mkdir(parents=True)
    log = [
        f"{stamp(T0)} INFO yaptracker.system_info: system: YapTracker v0.5.470 | Windows 11",
        f"{stamp(T0 + 60)} INFO yaptracker.matches: match 1 started (heroselect, COMPETITIVE, "
        "Circuit Royal)",
        f"{stamp(T0 + 61)} INFO yaptracker.reading_mode: reading: after (COMPETITIVE, match 1)",
        f"{stamp(T0 + 100)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median 60, "
        "p10 52, n=11 — running, in match, after; 30 ms CPU per read",  # hero select: left out
        f"{stamp(T0 + 62)} INFO yaptracker.capture.wgc: capture: asking Windows for 4 frames a "
        "second (in a match)",
        f"{stamp(T0 + 120)} INFO yaptracker.reader: chat reading: 4 frames, 90 ms CPU each "
        "(after 4); whole app: 20.0 % of a core",
        f"{stamp(T0 + 120)} INFO yaptracker.cpu_parts: cpu threads (in match): native 11.5 %, "
        "capture watcher 8.0 %, chat reader 2.5 %",
        f"{stamp(T0 + 121)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median 120, "
        "p10 110, n=11 — running, in match; 30 ms CPU per read",  # older: the mode before it
        f"{stamp(T0 + 181)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median 131, "
        "p10 120, n=11 — running, in match, light; 30 ms CPU per read",  # the line says (#444)
        f"{stamp(T0 + 190)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median 50, "
        "p10 40, n=3 — running, in match, after; 30 ms CPU per read",  # a partial minute: out
        f"{stamp(T0 + 400)} INFO yaptracker.matches: match 1: round 2 (same map, no result yet)",
        f"{stamp(T0 + 410)} INFO yaptracker.reader: chat reading: 2 line(s) seen twice but never "
        "stored: Pip: hi; Bo: yo",
        f"{stamp(T0 + 420)} INFO yaptracker.familiar: familiar face: player #7 (last met "
        "2026-10-09)",
        f"{stamp(T0 + 960)} INFO yaptracker.familiar: familiar face: player #9 (last met "
        "2026-10-02), after the match",
        f"{stamp(T0 + 950)} INFO yaptracker.reader: tidied match 1: 2 fixed, 1 found, 3 removed "
        "(light readings the best reader didn't confirm: repeats, pieces)",
        f"{stamp(T0 + 1000)} INFO yaptracker.matches: match 2 started (heroselect, GEWERTET, "
        "Circuit Royal)",
        f"{stamp(T0 + 2000)} INFO yaptracker.evenings: evening 2026-10-12: 2 matches (hero select "
        "2, gap 0, hand 0) · whole app 20 % of a core",
        f"{stamp(T0 + 2001)} INFO yaptracker.evenings: evening 2026-10-01: 5 matches (hero select "
        "5, gap 0, hand 0) (filled in)",
        f"{stamp(T0 + 5 * 3600)} INFO yaptracker.reader: chat reading: 4 frames, 90 ms CPU each "
        "(light 4); whole app: 30.0 % of a core",  # 01:00: still this evening
        f"{stamp(T0 + 5 * 3600)} INFO yaptracker.cpu_parts: cpu threads (in match): native 4.5 %, "
        "pywebview-js 1.5 %",
        f"{stamp(T0 + 5 * 3600)} ERROR yaptracker.capture.watcher: capture failed",
        "Traceback (most recent call last):",  # no time: still that evening
        "PermissionError: [Errno 13] Permission denied: 'C:\\data\\config.json'",
        f"{stamp(T0 + 5 * 3600)} ERROR yaptracker.reader: reading the chat failed",
    ]
    if paused:  # after match 2 started: its hero select minute, then a full one
        at = log.index(next(line for line in log if "match 2 started" in line)) + 1
        log[at:at] = [
            f"{stamp(T0 + 1040)} INFO yaptracker.game_fps: game fps (Overwatch overlay): "
            "median 58, p10 50, n=11 — paused, in match; 30 ms CPU per read",
            f"{stamp(T0 + 1100)} INFO yaptracker.game_fps: game fps (Overwatch overlay): "
            "median 124, p10 118, n=11 — paused, in match; 30 ms CPU per read",
        ]
    (data / "logs" / "yaptracker.log.1").write_text(log[0] + "\n", encoding="utf-8")  # rotated
    (data / "logs" / "yaptracker.log.old").write_text("a copy, not a rotation", encoding="utf-8")
    (data / "logs" / "yaptracker.log").write_text("\n".join(log[1:]) + "\n", encoding="utf-8")
    return data


def test_the_report_answers_every_waiting_issue_with_ids_only(tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(evidence.tempfile, "tempdir", str(temp))
    text = evidence.report(data_folder(tmp_path, paused=True))
    assert list(temp.iterdir()) == []  # the copy of the database (names, chat) is gone
    assert "- 2026-10-12 (v0.5.470): whole app avg 25.0 % of a core (n=2)" in text  # 01:00 too
    assert "threads in match (2 min): native 8.0 %, capture watcher 4.0 %, chat reader 1.2 %, " \
        "pywebview-js 0.8 %" in text  # fmt: skip
    assert "seen but not stored 2" in text and "capture 4 fps in a match" in text
    assert "2026-10-12 v0.5.470 after running: 120 fps (n=1)" in text
    assert "2026-10-12 v0.5.470 light running: 131 fps (n=1)" in text
    assert "2026-10-12 v0.5.470 - paused: 124 fps (n=1)" in text  # paused: no mode
    assert (
        "verdict v0.5.470 after: Circuit Royal: running 120 vs paused 124 fps (3.2 %, 1/1 "
        "min): costs 3.2 % (within the 5 % bar)" in text
    )  # same map, hero select left out (#448)
    assert "Competitive matches: 2 (#1 2026-10-12, #2 2026-10-12)" in text  # German one too
    assert "Circuit Royal ×2" in text and "#1 round 2" in text  # Quick Play's not counted
    assert "of a Competitive match: 2026-10-12/" in text  # the ranked end sample, 2 s later
    assert "## #34 Acceptance evening (2026-10-12)" in text
    assert (
        "players with notes now: 1" in text
        and "familiar faces shown: 2 (after the match 1)" in text
    )
    assert "tidied match 1: 2 fixed, 1 found, 3 removed" in text
    assert "v0.5.470: evening 2026-10-12: 2 matches" in text
    assert "filled in later: evening 2026-10-01: 5 matches" in text
    assert "- 2026-10-12: config busy (#451) ×1, reading the chat failed (#452) ×1" in text
    for name in ("NoodleBonk", "Pip", "Bo:"):  # ids only, never a name
        assert name not in text, name


def test_no_paused_match_is_said_and_a_missing_db_is_no_crash(tmp_path):
    data = data_folder(tmp_path, paused=False)
    assert "no paused in-match samples (running median 120 fps, n=1)" in evidence.report(data)
    (data / "yaptracker.db").unlink()
    assert "## #34" in evidence.report(data)


def test_an_evening_runs_until_five_in_the_morning():
    assert evidence.evening_of("2026-10-13", "04:59:59") == "2026-10-12"
    assert evidence.evening_of("2026-10-13", "05:00:00") == "2026-10-13"


def fps(t: float, median: int, state: str, n: int = 11) -> str:
    return (f"{stamp(t)} INFO yaptracker.game_fps: game fps (Overwatch overlay): median {median}, "
            f"p10 {median - 10}, n={n} — {state}, in match; 30 ms CPU per read")  # fmt: skip


def match_line(t: float, text: str) -> str:
    return f"{stamp(t)} INFO yaptracker.matches: match {text}"


def test_fps_is_compared_on_the_same_map_only():
    """#448: 110 running vs 140 paused said 21 % when the maps differed; King's Row ran at 140
    either way. A gap start taken over by hero select and a map read off the end screen count."""
    log = [
        f"{stamp(T0)} INFO yaptracker.system_info: system: YapTracker v0.5.487 | Windows 11",
        match_line(T0 + 10, "153 started (heroselect, UNRANKED, King's Row)"),
        fps(T0 + 60, 61, "paused"), fps(T0 + 120, 140, "paused"), fps(T0 + 180, 141, "paused"),
        match_line(T0 + 600, "154 started (gap, None, None)"),
        match_line(T0 + 606, "154: hero select (None, None) takes over its start (gap)"),
        fps(T0 + 660, 60, "running"), fps(T0 + 720, 105, "running"),
        match_line(T0 + 900, "154: map from the end screen: Junkertown"),
        match_line(T0 + 1000, "155 started (heroselect, UNRANKED, King's Row)"),
        fps(T0 + 1060, 59, "running"), fps(T0 + 1120, 140, "running"),
        fps(T0 + 1180, 141, "running"), fps(T0 + 1200, 90, "running", n=4),
    ]  # fmt: skip
    found = evidence.scan(log)
    (verdict,) = evidence.fps_verdicts(found)
    assert verdict.startswith("v0.5.487 ?: King's Row: running 140 vs paused 140 fps (0.0 %, 2/2")
    assert "Junkertown" not in verdict and "within the 5 % bar" in verdict


def test_paused_only_on_another_map_says_so_instead_of_a_number():
    log = [
        match_line(T0, "1 started (heroselect, UNRANKED, Oasis)"),
        fps(T0 + 60, 60, "paused"), fps(T0 + 120, 150, "paused"),
        match_line(T0 + 600, "2 started (heroselect, UNRANKED, Nepal)"),
        fps(T0 + 660, 60, "running"), fps(T0 + 720, 120, "running"),
    ]  # fmt: skip
    (verdict,) = evidence.fps_verdicts(evidence.scan(log))
    assert verdict == "v? ?: no same-map running minutes: paused on Oasis (running median 120 " \
        "fps, n=1)"  # fmt: skip
