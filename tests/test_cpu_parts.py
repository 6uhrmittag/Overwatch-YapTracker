"""Where the CPU goes (#302): every part's share of one core once a minute, the rest, the
whole app."""

import logging
import threading
import time

from yaptracker.cpu_parts import CpuParts, thread_seconds


def test_one_line_a_minute_with_every_part_the_rest_and_the_whole(caplog):
    clock, cpu = [0.0], [100.0]
    parts = CpuParts(lambda: clock[0], lambda: cpu[0])
    parts.tick()  # starts the minute
    parts.add("reading", 9.6)
    parts.add("change detection", 6.0)
    parts.add("capture", 1.8)
    with caplog.at_level(logging.INFO, logger="yaptracker.cpu_parts"):
        clock[0], cpu[0] = 30.0, 110.0
        parts.tick()  # half a minute: nothing yet
        assert not caplog.records
        clock[0], cpu[0] = 60.0, 100.0 + 21.0  # 21 s of CPU in 60 s = 35 % of a core
        parts.tick()
    (line,) = [r.getMessage() for r in caplog.records]
    assert line == (
        "cpu parts: reading 16.0 %, change detection 10.0 %, match signals 0.0 %, "
        "debug samples 0.0 %, capture 3.0 %, chat recorder 0.0 % - rest 6.0 % (whole app 35.0 %)"
    )


def test_a_part_counts_its_own_threads_cpu():
    parts = CpuParts(lambda: 0.0, lambda: 0.0)
    deadline = time.perf_counter() + 5
    with parts.part("match signals"):
        started = time.thread_time()
        # Real work on this thread until its CPU time moves: Windows counts in ~16 ms steps (#398)
        while time.thread_time() == started and time.perf_counter() < deadline:
            sum(i * i for i in range(10_000))
    assert parts._spent["match signals"] > 0


def test_the_line_says_the_state_of_its_minute(caplog):
    """In match / between matches / paused / no game (#351), as the FPS lines say it (#187)."""
    clock, state = [0.0], ["between matches"]
    parts = CpuParts(lambda: clock[0], lambda: clock[0] / 10)
    parts.state = lambda: state[0]
    parts.tick()
    with caplog.at_level(logging.INFO, logger="yaptracker.cpu_parts"):
        clock[0] = 30.0
        state[0] = "in match"
        parts.tick()
        clock[0] = 60.0
        parts.tick()  # crossed: both
        clock[0] = 120.0
        parts.tick()  # a whole minute in the match
    first, second = [r.getMessage() for r in caplog.records]
    assert first.startswith("cpu parts (between matches + in match): reading 0.0 %")
    assert second.startswith("cpu parts (in match): ")


def test_a_second_line_splits_the_minute_by_thread(caplog):
    """#350: "rest" between matches is the biggest share and no part says why."""
    me = threading.get_native_id()
    clock, seconds = [0.0], {me: 5.0, 4242: 1.0, 4243: 0.1}  # 4242, 4243: not Python threads
    parts = CpuParts(lambda: clock[0], lambda: clock[0] / 10, threads=lambda: dict(seconds))
    parts.state = lambda: "between matches"
    parts.tick()
    with caplog.at_level(logging.INFO, logger="yaptracker.cpu_parts"):
        clock[0], seconds[me], seconds[4242], seconds[4243] = 60.0, 11.0, 2.8, 0.2
        parts.tick()
    name = threading.current_thread().name
    assert caplog.records[-1].getMessage() == (
        f"cpu threads (between matches): {name} 10.0 %, native 3.2 %"  # under 0.5 %: left out
    )


def test_this_process_threads_have_cpu_times():
    found = thread_seconds()
    assert threading.get_native_id() in found and all(s >= 0 for s in found.values())


def test_the_whole_app_counts_its_ocr_child(monkeypatch, caplog):
    """#563: OCR moved to a process of its own; its CPU is still the app's, in both lines."""
    import logging

    from yaptracker import cpu_parts, reader

    used = {"here": 10.0, "child": 100.0, "thread": 1.0}
    monkeypatch.setattr(cpu_parts.time, "process_time", lambda: used["here"])
    monkeypatch.setattr(cpu_parts.time, "thread_time", lambda: used["thread"])
    monkeypatch.setattr(cpu_parts, "children", lambda: used["child"])
    now = [0.0]
    parts = cpu_parts.CpuParts(clock=lambda: now[0], threads=lambda: {})
    parts.tick()
    started = reader._cpu_now()
    used.update(here=13.0, child=109.0, thread=1.5)  # a minute: 3 s here, 9 s in the child
    now[0] = 60.0
    with caplog.at_level(logging.INFO, logger="yaptracker.cpu_parts"):
        parts.add("reading", reader._cpu_now() - started)
    assert "reading 15.8 %" in caplog.text  # 0.5 s of the reader's thread + the child's 9 s
    assert "(whole app 20.0 %)" in caplog.text


def test_every_part_named_in_the_code_is_counted():
    """A CPU.part("...") name missing from PARTS crashed capture on every start (#663)."""
    import re
    from pathlib import Path

    from yaptracker import cpu_parts

    src = Path(cpu_parts.__file__).parent
    named = re.compile(r"""CPU\.(?:part|add)\(\s*["']([^"']+)["']""")
    names = {m for f in src.rglob("*.py") for m in named.findall(f.read_text("utf-8"))}
    assert names >= {"chat recorder", "change detection", "debug samples"}  # the scan finds them
    assert names <= set(cpu_parts.PARTS), names - set(cpu_parts.PARTS)


def test_an_unknown_part_never_raises_and_is_said_once(caplog):
    clock, cpu = [0.0], [0.0]
    parts = CpuParts(lambda: clock[0], lambda: cpu[0])
    parts.tick()
    with caplog.at_level(logging.INFO, logger="yaptracker.cpu_parts"):
        parts.add("no such part", 3.0)
        with parts.part("no such part"):
            pass
        clock[0], cpu[0] = 60.0, 6.0
        parts.tick()
    lines = [r.getMessage() for r in caplog.records]
    assert sum("unknown part 'no such part'" in line for line in lines) == 1
    assert "no such part" not in lines[-1] and "rest 10.0 %" in lines[-1]  # its time is rest
