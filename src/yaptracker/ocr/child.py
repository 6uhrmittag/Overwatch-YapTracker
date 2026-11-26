"""OCR in its own process (#563). In a match the game takes the cores; the chat reader's thread,
at the lowest priority, was put to sleep while it held Python's lock (the GIL), and capture,
watchdog and UI, all in the same process, waited for it. A child process has its own lock: it can
wait for a core as long as it must, and the main process still runs its millisecond jobs on time.

The picture goes over shared memory (a 4K chat box is ~5 MB: too much for a pipe every read),
the request and the lines read come back over a pipe. The child ends when the parent goes: its
pipe closes, also when the parent is killed.
"""

import contextlib
import logging
import multiprocessing
import os
import threading
import time
from collections.abc import Callable
from multiprocessing import shared_memory

import numpy as np

from yaptracker import priority
from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import UPSCALE, OcrLine, OcrUnavailable

log = logging.getLogger(__name__)
# How long an answer is waited for: making an engine (the child starts and loads the model) and
# a read. Long on purpose (#619): a slow child isn't a dead one. In a starved match a read took
# 10-35 s before it had a process of its own (Marv's log 2026-11-24: 0.5-3 s of CPU each, 1-3
# reads in some minutes), and the main process, which reads when the child gives no answer,
# takes as long and stalls capture with it. Only a child that hangs should run into these.
ANSWER_S, READ_S = 180.0, 120.0
# Set while a child starts: in the exe the child is the exe started again, and its logs.setup()
# must tell it from the window's process (which owns window.log).
CHILD_ENV = "YAPTRACKER_OCR_CHILD"


class ChildGone(RuntimeError):
    """The child died, hung or couldn't start: the caller reads in this process instead."""


class ChildFailed(RuntimeError):
    """The engine failed in the child (it can't make it, or a read raised): the child lives, but
    the main process may well read the picture, so the caller tries there."""


def _serve(conn, get: Callable[[str], object]) -> None:
    """The child's whole life: read the pictures it's asked to, until the parent goes."""
    # The game first (#187): below normal + efficiency mode (the exe's start did that already;
    # `python -m` didn't), and this thread, the one that reads, at the lowest priority, as the
    # chat reader's thread was while it read in the main process.
    priority.lower_process()
    priority.lower_this_thread()
    braked = True  # "as fast as it can" takes them off, and a change of mind back on (#652)
    block: shared_memory.SharedMemory | None = None
    while True:
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return  # the parent is gone (also killed): so are we
        if request is None:
            return
        name, memory, shape, accents, scale, brakes = request
        if brakes != braked:
            braked = brakes
            priority.brakes(brakes)
        if memory is None:  # no picture: only make the engine, so the first read doesn't wait
            reply = _read(get, name, None, accents, scale)
            try:
                conn.send((*reply, time.process_time()))
            except (BrokenPipeError, OSError):
                return
            continue
        try:
            if block is None or block.name != memory:
                if block is not None:
                    block.close()
                block = shared_memory.SharedMemory(name=memory)
            # a copy: the parent may write the next picture while an engine still holds this one
            image = np.ndarray(shape, np.uint8, buffer=block.buf).copy()
        except Exception as error:  # no picture, no reading: the parent starts a new child
            reply = ("gone", f"the picture didn't arrive: {error!r}")
        else:
            reply = _read(get, name, image, accents, scale)
        try:
            conn.send((*reply, time.process_time()))
        except (BrokenPipeError, OSError):
            return
        if reply[0] == "gone":
            return


def _read(get, name: str, image: np.ndarray | None, accents: bool, scale: float) -> tuple:
    try:
        engine = get(name)
    except OcrUnavailable as reason:
        return "unavailable", str(reason)
    except Exception as error:  # e.g. a model file is missing: not something to retry
        return "error", repr(error)
    if image is None:
        return "ok", []
    try:
        return "ok", engine.read(image, accents=accents, scale=scale)
    except OcrUnavailable as reason:
        return "unavailable", str(reason)
    except OSError as error:  # Windows OCR's "Operation aborted" (#452): the caller retries
        return "oserror", str(error)
    except Exception as error:  # anything else: said in the parent's log
        return "error", repr(error)


class OcrChild:
    """The parent's end: one child, one read at a time."""

    def __init__(self, get: Callable[[str], object] = ocr.get, answer_s: float = ANSWER_S,
                 read_s: float = READ_S) -> None:  # fmt: skip
        self._get, self._answer_s, self._read_s = get, answer_s, read_s
        self._made: set[str] = set()  # engines the running child has made: their reads are quick
        self._lock = threading.Lock()
        self._process: multiprocessing.process.BaseProcess | None = None
        self._conn = None
        self._block: shared_memory.SharedMemory | None = None
        self._stopped = False
        self._cpu = (0.0, 0.0)  # (of children that are gone, of the one running): one store
        self.pid: int | None = None
        # The child's FPS brakes (#652): off only for "as fast as it can"; sent with every read
        self.brakes: Callable[[], bool] = lambda: True

    def waits(self, answer_s: float, read_s: float) -> None:
        """Other limits than the defaults (the smoke test: it has 90 s in all)."""
        self._answer_s, self._read_s = answer_s, read_s

    @property
    def cpu_s(self) -> float:
        """CPU time used in children so far, for the "whole app" lines; it only ever grows."""
        return sum(self._cpu)

    def _start(self) -> None:
        # spawn everywhere (Windows has nothing else): tests on Linux run what Windows runs
        context = multiprocessing.get_context("spawn")
        ours, theirs = context.Pipe()
        process = context.Process(
            target=_serve, args=(theirs, self._get), name="ocr child", daemon=True
        )
        os.environ[CHILD_ENV] = "1"
        try:
            process.start()
        except BaseException:
            ours.close()
            raise
        finally:
            os.environ.pop(CHILD_ENV, None)
            theirs.close()  # ours is the only other end: the child sees it close when we go
        self._process, self._conn, self.pid = process, ours, process.pid

    def read(
        self, name: str, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        """Like OcrEngine.read, in the child. ChildGone: it couldn't start, died or took too
        long (it's ended; the next read starts a new one)."""
        image = np.ascontiguousarray(image, np.uint8)
        if not image.nbytes:
            return []  # nothing to read, and shared memory can't be empty
        return self._ask(name, image, accents, scale)

    def make(self, name: str) -> None:
        """The engine made in the child (its model loaded), like ocr.get(): OcrUnavailable if it
        can't run on this machine, ChildGone if the child can't."""
        self._ask(name, None, False, UPSCALE)

    def _ask(self, name: str, image: np.ndarray | None, accents: bool, scale: float) -> list:
        brakes = bool(self.brakes())
        with self._lock:
            try:
                if self._stopped:
                    raise OSError("stopped")
                if self._process is None or not self._process.is_alive():
                    self._close()
                    self._start()
                if image is None:
                    self._conn.send((name, None, None, accents, scale, brakes))
                else:
                    if self._block is None or self._block.size < image.nbytes:
                        self._free()
                        self._block = shared_memory.SharedMemory(create=True, size=image.nbytes)
                    np.ndarray(image.shape, np.uint8, buffer=self._block.buf)[:] = image
                    self._conn.send((name, self._block.name, image.shape, accents, scale, brakes))
                wait = self._read_s if image is not None and name in self._made else self._answer_s
                if not self._conn.poll(wait):
                    raise TimeoutError(f"no answer in {wait:g} s")
                kind, result, cpu = self._conn.recv()
                if kind == "gone":
                    raise OSError(result)
            except Exception as error:  # a broken pipe, a failed start, pickling: all the same
                self._close()
                raise ChildGone(f"{type(error).__name__}: {error}") from error
            except BaseException:  # Ctrl+C mid-read: its answer mustn't become the next one's
                self._close()
                raise
            self._cpu = (self._cpu[0], cpu)
            if kind == "ok":
                self._made.add(name)
        if kind == "ok":
            return result
        if kind == "unavailable":
            raise OcrUnavailable(result)
        if kind == "oserror":
            raise OSError(result)
        raise ChildFailed(f"OCR failed in its own process: {result}")

    def stop(self) -> None:
        """For good (the app is closing). A read still waiting for its answer ends at once
        with ChildGone: the child is killed first, not waited for behind the read's lock; again
        and again, in case a read was just starting one."""
        self._stopped = True
        while True:
            process = self._process
            if process is not None:
                with contextlib.suppress(Exception):  # gone already, or never started
                    process.kill()
            if self._lock.acquire(timeout=0.2):
                break
        try:
            self._close()
        finally:
            self._lock.release()

    def _close(self) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = self.pid = None
        self._cpu = (sum(self._cpu), 0.0)
        self._made = set()
        if conn is not None:
            with contextlib.suppress(OSError, ValueError):  # it may be gone already
                conn.send(None)
            conn.close()
        if process is not None:
            process.join(1.0)
            if process.is_alive():
                process.kill()
                process.join(1.0)
        self._free()

    def _free(self) -> None:
        block, self._block = self._block, None
        if block is not None:
            block.close()
            block.unlink()


GONE_LIMIT = 3  # children lost in a row before reading stays in this process for a while
RETRY_S = 600.0  # ...this long; then a child is tried again


class _Engine:
    """An OcrEngine for the chat reader: read() runs in the child."""

    def __init__(self, name: str, owner: "ChildEngines") -> None:
        self.name, self._owner = name, owner

    def read(
        self, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        return self._owner.read(self.name, image, accents, scale)

    def read_line(self, image: np.ndarray) -> str:
        return self._owner.local(self.name).read_line(image)  # milliseconds: not worth the trip


class ChildEngines:
    """ocr.get() for the chat reader (#563): engines that read in the child, and in this process
    whenever the child can't (it couldn't start, died, hung): a read is never lost to it, and the
    log says where it was read. GONE_LIMIT children lost in a row: this process reads for
    RETRY_S, then a child gets another try."""

    def __init__(self, child: OcrChild | None = None,
                 local: Callable[[str], object] = ocr.get,
                 clock: Callable[[], float] = time.monotonic,
                 brakes: Callable[[], bool] | None = None) -> None:  # fmt: skip
        self.child = child or OcrChild()
        if brakes is not None:
            self.child.brakes = brakes
        self.local, self._clock = local, clock
        self._engines: dict[str, _Engine] = {}
        self._gone, self._retry_at = 0, 0.0
        self._said: set[str] = set()  # engines whose first read in the child is in the log
        self._stopped = False

    def get(self, name: str) -> _Engine:
        """Like ocr.get(): blocks while the engine is made (in the child), and raises
        OcrUnavailable where it can't run."""
        if name not in self._engines:
            if not self._in_child(lambda: self.child.make(name)):
                self.local(name)
            self._engines[name] = _Engine(name, self)
        return self._engines[name]

    def read(self, name: str, image: np.ndarray, accents: bool, scale: float) -> list[OcrLine]:
        lines: list[OcrLine] = []

        def read() -> None:
            lines.extend(self.child.read(name, image, accents, scale))

        if not self._in_child(read):
            # heavy work in the main process after all: at the lowest priority while it lasts,
            # as the reader's thread was before (#187); the game still goes first
            with priority.lowest_for_now():
                return self.local(name).read(image, accents=accents, scale=scale)
        if name not in self._said:
            self._said.add(name)
            log.info("ocr child: %s reads the chat in its own process (pid %s)", name,
                     self.child.pid)  # fmt: skip
        return lines

    def _in_child(self, ask: Callable[[], None]) -> bool:
        """True: the child did it. False: do it in this process (said in the log)."""
        if self._stopped or self._clock() < self._retry_at:
            return False  # quitting: the last read is done here, without a word
        try:
            ask()
        except (ChildGone, ChildFailed) as gone:
            if self._stopped:
                return False
            self._gone += 1
            self._said.clear()  # a new child says again that it reads
            if self._gone >= GONE_LIMIT:
                self._gone, self._retry_at = 0, self._clock() + RETRY_S
                log.warning(
                    "ocr child: lost %d times in a row (%s): reading in the main process for"
                    " %.0f min, then I try again", GONE_LIMIT, gone, RETRY_S / 60,
                )  # fmt: skip
            else:
                log.warning("ocr child: %s: this one is read in the main process", gone)
            return False
        self._gone = 0
        return True

    def reads_in_child(self) -> bool:
        """The child reads now (False: the main process does, for a while or for good)."""
        return not self._stopped and self._clock() >= self._retry_at

    def warm_up(self, name: str) -> None:
        """The child started and the engine made in it, in the background: the evening's first
        chat line doesn't wait for the model."""

        def make() -> None:
            try:
                self.get(name)
            except Exception as error:  # e.g. no OCR language: the reader says so when it reads
                log.warning("ocr child: %s can't start: %s", name, error)

        threading.Thread(target=make, name=f"load OCR {name} (child)", daemon=True).start()

    def stop(self) -> None:
        self._stopped = True
        self.child.stop()
