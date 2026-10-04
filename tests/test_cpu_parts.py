"""Where the CPU goes (#302): every part's share of one core once a minute, the rest, the
whole app."""

import logging

from yaptracker.cpu_parts import CpuParts


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
