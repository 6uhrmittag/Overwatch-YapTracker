"""Where the CPU goes (#302): every part's share of one core once a minute, the rest, the
whole app."""

import logging
import threading

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
        "debug samples 0.0 %, capture 3.0 % - rest 6.0 % (whole app 35.0 %)"
    )


def test_a_part_counts_its_own_threads_cpu():
    parts = CpuParts(lambda: 0.0, lambda: 0.0)
    with parts.part("match signals"):
        sum(i * i for i in range(200_000))  # some real work on this thread
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
