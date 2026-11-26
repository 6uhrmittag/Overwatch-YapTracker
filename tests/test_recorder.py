"""The chat recorder (#654): one evening of the chat box, to count lost lines."""

import json
import time

import numpy as np

from yaptracker import config, images
from yaptracker.recorder import ChatRecorder


def picture(fill=7):
    return np.full((40, 60, 3), fill, np.uint8)


class Clock:
    def __init__(self):
        self.now = time.mktime((2026, 11, 27, 20, 0, 0, 0, 0, -1))

    def __call__(self):
        return self.now


def recorder(tmp_path, until, clock, **kwargs):
    off = lambda: until.__setitem__(0, 0)  # noqa: E731
    r = ChatRecorder(tmp_path / "recordings", lambda: until[0], stop=off, clock=clock,
                     free=lambda folder: 10**12, **kwargs)  # fmt: skip
    r.start()
    return r


def wait_for(check, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return check()


def run_folder(tmp_path):
    (day,) = (tmp_path / "recordings").iterdir()
    (run,) = day.iterdir()
    return run


def test_off_by_default_records_nothing(tmp_path):
    clock, until = Clock(), [0.0]
    r = recorder(tmp_path, until, clock)
    r.frame(picture(), True, match=1)
    r.signals({"banner": picture()})
    r.close()
    assert not any((tmp_path / "recordings").rglob("*.webp"))
    assert config.record_chat_until() == 0.0  # the setting's default


def test_changed_frames_are_kept_lossless_and_every_frame_is_in_the_index(tmp_path):
    clock, until = Clock(), [0.0]
    until[0] = clock.now + 3600
    r = recorder(tmp_path, until, clock)
    r.frame(picture(1), True, match=5, mode="best")
    clock.now += 0.5
    r.frame(picture(1), False, match=5, mode="best")
    clock.now += 0.5
    r.frame(picture(2), True, match=5, mode="best")
    r.signals({"banner": picture(9), "overview": picture(3)})
    r.close()
    run = run_folder(tmp_path)
    index = [json.loads(line) for line in (run / "frames.jsonl").read_text().splitlines()]
    assert [(e["changed"], "picture" in e, e["match"], e["mode"]) for e in index] == [
        (True, True, 5, "best"), (False, False, 5, "best"), (True, True, 5, "best")]  # fmt: skip
    kept = images.read(run / index[2]["picture"])
    assert kept is not None and (kept == picture(2)).all()  # lossless
    assert [p.name.split("-", 1)[1] for p in (run / "signals").iterdir()] == ["banner.png"]
    assert wait_for(lambda: (r.size_bytes() or 0) > 0)


def test_it_switches_itself_off_when_the_evening_is_over(tmp_path):
    clock, until = Clock(), [0.0]
    until[0] = clock.now + 10
    r = recorder(tmp_path, until, clock)
    assert r.on()
    clock.now += 11
    assert not r.on() and until[0] == 0  # saved as off
    r.close()


def test_it_pauses_on_a_nearly_full_disk(tmp_path):
    clock, until = Clock(), [Clock().now + 3600]
    r = ChatRecorder(tmp_path / "recordings", lambda: until[0], clock=clock,
                     free=lambda folder: 1_000_000_000)  # fmt: skip
    assert not r.on()


def test_recordings_older_than_14_days_are_deleted_at_start(tmp_path):
    clock, until = Clock(), [0.0]
    old = tmp_path / "recordings" / "2026-11-01" / "20-00-00"
    recent = tmp_path / "recordings" / "2026-11-20" / "20-00-00"
    for folder in (old, recent):
        folder.mkdir(parents=True)
        (folder / "frames.jsonl").write_text("{}\n")
    r = recorder(tmp_path, until, clock)
    assert wait_for(lambda: r.size_bytes() is not None)
    r.close()
    assert not old.parent.exists() and recent.exists()


def test_a_full_queue_drops_frames_and_says_how_many(tmp_path, monkeypatch):
    from yaptracker import recorder as recorder_module

    clock, until = Clock(), [Clock().now + 3600]
    monkeypatch.setattr(recorder_module, "QUEUE", 2)
    r = ChatRecorder(tmp_path / "recordings", lambda: until[0], clock=clock,
                     free=lambda folder: 10**12)  # fmt: skip
    for n in range(5):  # no writer yet: the queue fills
        clock.now += 0.5
        r.frame(picture(n), True)
    r.start()
    clock.now += 0.5
    assert wait_for(lambda: r._queue.qsize() == 0)
    r.frame(picture(9), True)
    r.close()
    index = [json.loads(line) for line in (run_folder(tmp_path) / "frames.jsonl").read_text()
             .splitlines()]  # fmt: skip
    assert len(index) == 3 and index[-1]["dropped_before"] == 3


def test_the_setting_saves_until_when(tmp_path):
    config.save_record_chat_until(1234.5)
    assert config.record_chat_until() == 1234.5
    config.save_record_chat_until(0)
    assert config.record_chat_until() == 0.0


def test_switched_on_again_later_is_a_recording_of_its_own(tmp_path):
    """Review of #654: the app runs for days; Friday's recording isn't added to Monday's."""
    clock, until = Clock(), [Clock().now + 3600]
    r = recorder(tmp_path, until, clock)
    r.frame(picture(1), True)
    until[0] = 0.0
    clock.now += 5
    r.refresh()
    r.frame(picture(2), True)  # off: nothing
    clock.now += 3 * 86400
    until[0] = clock.now + 3600
    r.refresh()
    r.frame(picture(3), True)
    r.close()
    runs = sorted(run for day in (tmp_path / "recordings").iterdir() for run in day.iterdir())
    assert len(runs) == 2
    assert [len((run / "frames.jsonl").read_text().splitlines()) for run in runs] == [1, 1]


def test_above_the_cap_the_oldest_days_go_at_start_and_recording_pauses(tmp_path):
    clock, until = Clock(), [Clock().now + 3600]
    for day in ("2026-11-20", "2026-11-25"):
        folder = tmp_path / "recordings" / day / "20-00-00"
        folder.mkdir(parents=True)
        (folder / "frames.jsonl").write_bytes(b"x" * 600)
    r = recorder(tmp_path, until, clock, cap_bytes=1000)
    assert wait_for(lambda: r.size_bytes() is not None)
    assert not (tmp_path / "recordings" / "2026-11-20").exists()
    assert (tmp_path / "recordings" / "2026-11-25").exists() and r.on()
    r._bytes = 2000  # a long evening later
    assert not r.on()
    r.close()


def test_frames_dropped_at_the_end_are_still_counted_at_quit(tmp_path, monkeypatch):
    from yaptracker import recorder as recorder_module

    clock, until = Clock(), [Clock().now + 3600]
    monkeypatch.setattr(recorder_module, "QUEUE", 1)
    r = ChatRecorder(tmp_path / "recordings", lambda: until[0], clock=clock,
                     free=lambda folder: 10**12)  # fmt: skip
    r._run = ((1, clock.now), tmp_path)  # a recording is open (close() only adds to one)
    r.frame(picture(1), True)
    r.frame(picture(2), True)  # dropped: the queue holds one
    r.start()
    r.close()
    index = [json.loads(line) for line in (tmp_path / "frames.jsonl").read_text().splitlines()]
    assert index[-1]["end"] and index[-1]["dropped_before"] == 1
