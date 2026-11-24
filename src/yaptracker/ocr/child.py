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

from yaptracker.ocr import engine as ocr
from yaptracker.ocr.engine import UPSCALE, OcrLine, OcrUnavailable

log = logging.getLogger(__name__)
# A read waits this long for its answer. The first one loads the model in the child (seconds),
# and a starved child may need long: a child that takes longer is taken for stuck.
ANSWER_S = 60.0


class ChildGone(RuntimeError):
    """The child died, hung or couldn't start: the caller reads in this process instead."""


def _serve(conn, get: Callable[[str], object]) -> None:
    """The child's whole life: read the pictures it's asked to, until the parent goes."""
    block: shared_memory.SharedMemory | None = None
    while True:
        try:
            request = conn.recv()
        except (EOFError, OSError):
            return  # the parent is gone (also killed): so are we
        if request is None:
            return
        name, memory, shape, accents, scale = request
        try:
            if block is None or block.name != memory:
                if block is not None:
                    block.close()
                block = shared_memory.SharedMemory(name=memory)
            # a copy: the parent may write the next picture while an engine still holds this one
            image = np.ndarray(shape, np.uint8, buffer=block.buf).copy()
            reply = ("ok", get(name).read(image, accents=accents, scale=scale))
        except OcrUnavailable as reason:
            reply = ("unavailable", str(reason))
        except OSError as error:  # Windows OCR's "Operation aborted" (#452): the caller retries
            reply = ("oserror", str(error))
        except Exception as error:  # anything else: said in the parent's log
            reply = ("error", repr(error))
        try:
            conn.send((*reply, time.process_time()))
        except (BrokenPipeError, OSError):
            return


class OcrChild:
    """The parent's end: one child, one read at a time."""

    def __init__(self, get: Callable[[str], object] = ocr.get, answer_s: float = ANSWER_S) -> None:
        self._get, self._answer_s = get, answer_s
        self._lock = threading.Lock()
        self._process: multiprocessing.process.BaseProcess | None = None
        self._conn = None
        self._block: shared_memory.SharedMemory | None = None
        self.cpu_s = 0.0  # CPU time the child has used so far, for the "whole app" lines
        self.pid: int | None = None

    def _start(self) -> None:
        # spawn everywhere (Windows has nothing else): tests on Linux run what Windows runs
        context = multiprocessing.get_context("spawn")
        self._conn, theirs = context.Pipe()
        self._process = context.Process(
            target=_serve, args=(theirs, self._get), name="ocr child", daemon=True
        )
        self._process.start()
        theirs.close()  # ours is the only other end: the child sees it close when we go
        self.pid, self.cpu_s = self._process.pid, 0.0

    def read(
        self, name: str, image: np.ndarray, accents: bool = False, scale: float = UPSCALE
    ) -> list[OcrLine]:
        """Like OcrEngine.read, in the child. ChildGone: it died or took too long (it's ended;
        the next read starts a new one)."""
        image = np.ascontiguousarray(image, np.uint8)
        with self._lock:
            try:
                if self._process is None or not self._process.is_alive():
                    self._close()
                    self._start()
                if self._block is None or self._block.size < image.nbytes:
                    self._free()
                    self._block = shared_memory.SharedMemory(create=True, size=image.nbytes)
                np.ndarray(image.shape, np.uint8, buffer=self._block.buf)[:] = image
                self._conn.send((name, self._block.name, image.shape, accents, scale))
                if not self._conn.poll(self._answer_s):
                    raise TimeoutError(f"no answer in {self._answer_s:g} s")
                kind, result, cpu = self._conn.recv()
            except (EOFError, OSError, TimeoutError) as error:  # OSError: a broken pipe too
                self._close()
                raise ChildGone(f"{type(error).__name__}: {error}") from error
            self.cpu_s = cpu
        if kind == "ok":
            return result
        if kind == "unavailable":
            raise OcrUnavailable(result)
        if kind == "oserror":
            raise OSError(result)
        raise RuntimeError(f"OCR failed in its own process: {result}")

    def stop(self) -> None:
        with self._lock:
            self._close()

    def _close(self) -> None:
        process, conn = self._process, self._conn
        self._process = self._conn = self.pid = None
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


def round_trip(name: str, image: np.ndarray, get: Callable[[str], object] = ocr.get) -> str:
    """The spike (#563): one picture to a new child and back, timed and logged; the text read."""
    child = OcrChild(get)
    try:
        started = time.monotonic()
        lines = child.read(name, image)
        first = time.monotonic() - started
        started = time.monotonic()
        child.read(name, image)
        again = time.monotonic() - started
        log.info("ocr child: pid %s (parent %d) read a %dx%d picture with %s over shared memory:"
                 " first read %.0f ms (with starting and the model), the next %.0f ms, %.1f s of"
                 " its own CPU", child.pid, os.getpid(), image.shape[1], image.shape[0], name,
                 1000 * first, 1000 * again, child.cpu_s)  # fmt: skip
        return " ".join(line.text for line in lines)
    finally:
        child.stop()
