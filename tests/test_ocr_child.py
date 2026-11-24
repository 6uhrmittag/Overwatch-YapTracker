"""OCR in its own process (#563): a picture there and back over shared memory. The child is
spawned, as on Windows, so these run what the exe runs."""

import logging
import os
import time

import numpy as np
import pytest

from yaptracker.capture.source import Region
from yaptracker.ocr.child import GONE_LIMIT, RETRY_S, ChildEngines, ChildGone, OcrChild, round_trip
from yaptracker.ocr.engine import OcrLine, OcrUnavailable


class Echo:
    """A fake engine that proves the child saw the very picture: its size, sum and its pid."""

    def read(self, image, accents=False, scale=2.0):
        text = f"{image.shape[1]}x{image.shape[0]} sum {int(image.sum())} pid {os.getpid()}"
        return [OcrLine(text, 0.99, Region(1, 2, 3, 4), parts=(("word", Region(5, 6, 7, 8)),)),
                OcrLine(f"accents {accents} scale {scale}", 0.5, Region(0, 0, 1, 1))]  # fmt: skip


class Aborts:
    def read(self, image, accents=False, scale=2.0):
        raise OSError("Operation aborted")  # Windows OCR now and then (#452)


def get(name: str):  # module level: the spawned child imports it by name
    if name == "none":
        raise OcrUnavailable("no OCR language installed")
    if name == "aborts":
        return Aborts()
    if name == "no model":
        raise FileNotFoundError("rec.onnx")
    if name == "broken":
        raise ValueError("bad model")
    if name == "dies":
        os._exit(3)
    if name == "hangs":
        time.sleep(30)
    return Echo()


@pytest.fixture
def child():
    child = OcrChild(get, answer_s=20.0)
    yield child
    child.stop()


def picture(width=615, height=395, fill=7):
    return np.full((height, width, 3), fill, np.uint8)


def test_a_picture_goes_to_the_child_and_its_lines_come_back(child):
    first, second = child.read("echo", picture(), accents=True, scale=1.33)
    assert first.text == f"615x395 sum {615 * 395 * 3 * 7} pid {child.pid}"
    assert child.pid != os.getpid()
    assert first.box == Region(1, 2, 3, 4) and first.parts == (("word", Region(5, 6, 7, 8)),)
    assert second.text == "accents True scale 1.33"
    assert child.cpu_s > 0


def test_the_next_pictures_reuse_the_child_also_bigger_ones(child):
    pid = child.read("echo", picture())[0].text.split()[-1]
    big = child.read("echo", picture(3840 // 4, 2160 // 4, fill=3))[0].text  # a new, bigger block
    small = child.read("echo", picture(64, 48, fill=1))[0].text  # fits in the block it has
    assert big == f"960x540 sum {960 * 540 * 3 * 3} pid {pid}"
    assert small == f"64x48 sum {64 * 48 * 3} pid {pid}"


def test_a_view_of_a_bigger_frame_is_sent_as_it_looks(child):
    frame = np.arange(40 * 60 * 3, dtype=np.uint8).reshape(40, 60, 3)
    crop = frame[5:25, 10:50]  # not contiguous in memory
    assert child.read("echo", crop)[0].text.startswith(f"40x20 sum {int(crop.sum())} ")


def test_the_engines_own_errors_come_back_as_themselves(child):
    with pytest.raises(OcrUnavailable, match="no OCR language installed"):
        child.read("none", picture())
    with pytest.raises(OSError, match="Operation aborted"):
        child.read("aborts", picture())
    with pytest.raises(RuntimeError, match="bad model"):
        child.read("broken", picture())
    with pytest.raises(RuntimeError, match="rec.onnx"):  # no engine: nothing a retry fixes
        child.read("no model", picture())
    assert child.read("echo", picture())  # and the child lives on


def test_a_child_that_died_is_said_and_the_next_read_starts_a_new_one(child):
    old = child.read("echo", picture())[0].text.split()[-1]
    with pytest.raises(ChildGone):
        child.read("dies", picture())
    new = child.read("echo", picture())[0].text.split()[-1]
    assert new != old


def test_a_child_that_hangs_is_ended(child):
    child.read("echo", picture())  # started with a generous limit: a loaded runner is slow
    child._answer_s = 1.0
    process = child._process
    with pytest.raises(ChildGone, match="no answer in 1 s"):
        child.read("hangs", picture())
    assert not process.is_alive()


def test_stopping_doesnt_wait_for_a_read_in_flight(child):
    """Review: quitting waited up to a minute behind a starved child's read."""
    import threading

    child.read("echo", picture())
    failed = []

    def read():
        try:
            child.read("hangs", picture())
        except ChildGone as gone:
            failed.append(gone)

    thread = threading.Thread(target=read)
    thread.start()
    time.sleep(0.5)  # the read is waiting for its answer now
    started = time.monotonic()
    child.stop()
    thread.join(5.0)
    assert time.monotonic() - started < 5.0 and len(failed) == 1
    with pytest.raises(ChildGone):  # stopped for good: no new child while the app closes
        child.read("echo", picture())


def test_a_child_that_cant_start_is_child_gone_every_time(child, monkeypatch):
    """Review: an AssertionError from joining a process that never started."""
    import multiprocessing.context

    def no_start(self):
        raise OSError("CreateProcess failed")

    monkeypatch.setattr(multiprocessing.context.SpawnProcess, "start", no_start)
    for _ in range(2):
        with pytest.raises(ChildGone, match="CreateProcess failed"):
            child.read("echo", picture())
    assert os.environ.get("YAPTRACKER_OCR_CHILD") is None


def test_a_picture_that_doesnt_arrive_ends_the_child_instead_of_a_retry(child):
    """Review: a missing block came back as the OSError that Windows OCR's retry is for."""
    child.read("echo", picture())
    process = child._process
    child._block.unlink()  # the child can't open the next, bigger one under this name
    name = child._block.name
    child._block.close()
    child._block = type(
        "Gone",
        (),
        {
            "size": 10**9,
            "name": name,
            "buf": bytearray(10**6),
            "close": lambda self: None,
            "unlink": lambda self: None,
        },
    )()
    child._conn.send(("echo", "no-such-block", (4, 4, 3), False, 2.0))
    kind, why, _ = child._conn.recv()
    assert kind == "gone" and "didn't arrive" in why
    process.join(10.0)
    assert not process.is_alive()
    child._block = None


def test_cpu_time_only_grows_also_over_a_new_child(child):
    child.read("echo", picture())
    before = child.cpu_s
    with pytest.raises(ChildGone):
        child.read("dies", picture())
    assert child.cpu_s == before
    child.read("echo", picture())
    assert child.cpu_s > before


def test_an_empty_picture_has_no_lines_and_needs_no_child(child):
    assert child.read("echo", np.zeros((0, 10, 3), np.uint8)) == []
    assert child.pid is None


def test_the_child_ends_when_its_parents_pipe_closes(child):
    """Also when the parent is killed: the pipe is all that holds the child."""
    child.read("echo", picture())
    process = child._process
    child._conn.close()  # what the parent's death looks like from the child
    process.join(10.0)
    assert not process.is_alive()
    child._conn = child._process = None  # nothing left to stop


def test_the_spike_logs_one_round_trip(caplog):
    with caplog.at_level(logging.INFO, logger="yaptracker.ocr.child"):
        text = round_trip("echo", picture(), get)
    assert text.startswith("615x395 sum ")
    assert "read a 615x395 picture with echo over shared memory: first read" in caplog.text


class Local:
    """What the main process would read: tells the two apart in the tests."""

    def __init__(self, name):
        self.name = name

    def read(self, image, accents=False, scale=2.0):
        return [OcrLine(f"read here by {self.name}", 0.9, Region(0, 0, 1, 1))]

    def read_line(self, image):
        return "a line read here"


def local(name: str):
    if name == "none":
        raise OcrUnavailable("no OCR language installed")
    return Local(name)


def test_the_readers_engine_reads_in_the_child_and_says_so_once(child, caplog):
    engines = ChildEngines(child, local)
    with caplog.at_level(logging.INFO, logger="yaptracker.ocr.child"):
        engine = engines.get("echo")
        first = engine.read(picture(), scale=1.5)
        engine.read(picture())
    assert first[0].text.endswith(f"pid {child.pid}") and first[1].text == "accents False scale 1.5"
    assert caplog.text.count("echo reads the chat in its own process") == 1
    assert engines.get("echo") is engine
    assert engine.read_line(picture()) == "a line read here"  # a signal strip: not worth the trip


def test_an_engine_that_cant_run_here_is_unavailable_at_get_like_before(child):
    """ReadingMode falls back from light to best on exactly this."""
    engines = ChildEngines(child, local)
    with pytest.raises(OcrUnavailable, match="no OCR language installed"):
        engines.get("none")
    with pytest.raises(OcrUnavailable):
        engines.get("none")  # asked again: not remembered as fine


def test_a_lost_child_costs_no_read_and_after_three_the_main_process_reads_for_a_while(caplog):
    now = [1000.0]
    child = OcrChild(get, answer_s=20.0)
    engines = ChildEngines(child, local, clock=lambda: now[0])
    try:
        with caplog.at_level(logging.INFO, logger="yaptracker.ocr.child"):
            assert engines.get("echo").read(picture())[0].text.startswith("615x395")
            dies = engines.get("dies")  # the child dies making it: made here instead
            for _ in range(GONE_LIMIT - 1):
                assert dies.read(picture())[0].text == "read here by dies"
            assert caplog.text.count("this one is read in the main process") == GONE_LIMIT - 1
            assert f"lost {GONE_LIMIT} times in a row" in caplog.text
            pid = child.pid
            assert engines.get("echo").read(picture())[0].text == "read here by echo"
            assert child.pid == pid  # no child is even tried for ten minutes
            now[0] += RETRY_S
            assert engines.get("echo").read(picture())[0].text.startswith("615x395")
    finally:
        engines.stop()


def test_after_stop_everything_is_read_here(child):
    engines = ChildEngines(child, local)
    engine = engines.get("echo")
    engines.stop()
    assert engine.read(picture())[0].text == "read here by echo"
