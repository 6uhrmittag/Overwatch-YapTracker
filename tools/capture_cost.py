"""What does capturing cost when Windows sends every frame? (#248) Windows only, CI or by hand.

    python tools/capture_cost.py [--seconds 10]

Opens a window that redraws itself as fast as it can (in its own process, so its CPU doesn't
count), then measures in this process, per mode: frames per second Windows delivered, frames
used, and CPU per second and per delivered frame.

    idle     no capture (what this process costs anyway)
    skip     WGC window capture, the callback returns at once (what Windows 10 pays for every
             frame it sends that YapTracker doesn't want)
    use      WGC window capture, every frame's chat box cropped and copied (no gate)
    gate     WGC window capture with YapTracker's own 4 fps gate (#216), as the app runs today
    burst    a WGC session opened for one frame every 250 ms, then closed
    gdi      a GDI copy (mss) of only the chat rectangle, 4 times a second (CLAUDE.md capture
             Fallback 2)
    rate     WGC with Windows' own 4 fps setting, where this Windows has it (11 24H2 and later)

Without the rate setting (Windows 10, Server 2022) "skip" shows whether a frame nobody uses
still costs a full readback. Read-only screen capture; nothing is sent to any window.
"""

import argparse
import subprocess
import sys
import threading
import time

CHAT = (55, 510, 615, 395)  # x, y, width, height at 2560x1440; scaled to the window below
ANIMATE = r"""
import tkinter as tk
root = tk.Tk(); root.title("capture-cost-target"); root.geometry("1280x720+0+0")
canvas = tk.Canvas(root, width=1280, height=720, bg="black", highlightthickness=0)
canvas.pack()
box = canvas.create_rectangle(0, 0, 200, 200, fill="orange")
step = [0]
def tick():
    step[0] = (step[0] + 7) % 1080
    canvas.coords(box, step[0], 100, step[0] + 200, 300)
    canvas.itemconfig(box, fill="#%02x8030" % (step[0] % 256))
    root.after(1, tick)
root.after(1, tick)
root.mainloop()
"""


def find_window(title: str) -> int:
    import ctypes

    for _ in range(100):
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.1)
    raise SystemExit(f"window {title!r} didn't open")


def measure(name: str, seconds: float, run) -> dict:
    counts = {"delivered": 0, "used": 0}
    cpu, wall = time.process_time(), time.perf_counter()
    run(seconds, counts)
    cpu, wall = time.process_time() - cpu, time.perf_counter() - wall
    delivered = counts["delivered"]
    return {"mode": name, "delivered/s": delivered / wall, "used/s": counts["used"] / wall,
            "cpu %": 100 * cpu / wall,
            "cpu ms/frame": 1000 * cpu / delivered if delivered else 0.0}  # fmt: skip


def wgc(hwnd: int, gate_s: float | None, use: bool, rate_ms: int | None = None):
    def run(seconds: float, counts: dict) -> None:
        from windows_capture import WindowsCapture

        stop, last = threading.Event(), {"at": 0.0}
        extra = {"minimum_update_interval": rate_ms} if rate_ms else {}
        capture = WindowsCapture(cursor_capture=None, draw_border=None, window_hwnd=hwnd,
                                 **extra)  # fmt: skip

        @capture.event
        def on_frame_arrived(frame, control) -> None:
            if stop.is_set():
                control.stop()
                return
            counts["delivered"] += 1
            now = time.monotonic()
            if gate_s is not None and now - last["at"] < gate_s:
                return
            last["at"] = now
            if use:
                h, w = frame.height, frame.width
                x, y, cw, ch = (int(v * s) for v, s in zip(CHAT, (w / 2560, h / 1440) * 2))
                frame.frame_buffer[y : y + ch, x : x + cw, :3].copy()
                counts["used"] += 1

        @capture.event
        def on_closed() -> None:
            stop.set()

        control = capture.start_free_threaded()
        time.sleep(seconds)
        stop.set()
        if not control.is_finished():
            control.stop()

    return run


def burst(hwnd: int):
    def run(seconds: float, counts: dict) -> None:
        from windows_capture import WindowsCapture

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            started, got = time.monotonic(), threading.Event()
            capture = WindowsCapture(cursor_capture=None, draw_border=None, window_hwnd=hwnd)

            @capture.event
            def on_frame_arrived(frame, control) -> None:
                if not got.is_set():
                    frame.frame_buffer[:4, :4, :3].copy()
                    counts["delivered"] += 1
                    counts["used"] += 1
                    got.set()
                control.stop()

            @capture.event
            def on_closed() -> None:
                got.set()

            control = capture.start_free_threaded()
            got.wait(2)
            if not control.is_finished():
                control.stop()
            time.sleep(max(0.0, 0.25 - (time.monotonic() - started)))

    return run


def gdi(hwnd: int):
    def run(seconds: float, counts: dict) -> None:
        import ctypes
        from ctypes import wintypes

        import mss
        import numpy as np

        rect = wintypes.RECT()
        ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin))
        w, h = rect.right, rect.bottom
        x, y, cw, ch = (int(v * s) for v, s in zip(CHAT, (w / 2560, h / 1440) * 2))
        area = {"left": origin.x + x, "top": origin.y + y, "width": cw, "height": ch}
        end = time.monotonic() + seconds
        with mss.mss() as screen:
            while time.monotonic() < end:
                np.asarray(screen.grab(area))[:, :, :3].copy()
                counts["delivered"] += 1
                counts["used"] += 1
                time.sleep(0.25)

    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    if sys.platform != "win32":
        sys.exit("Windows only.")
    from yaptracker.capture.wgc import windows_build

    target = subprocess.Popen([sys.executable, "-c", ANIMATE])
    try:
        hwnd = find_window("capture-cost-target")
        time.sleep(1.0)
        modes = [("idle", lambda s, c: time.sleep(s)), ("skip", wgc(hwnd, None, False)),
                 ("use", wgc(hwnd, None, True)), ("gate", wgc(hwnd, 0.225, True)),
                 ("burst", burst(hwnd)), ("gdi", gdi(hwnd))]  # fmt: skip
        if windows_build() >= 26100:
            modes.append(("rate", wgc(hwnd, None, True, rate_ms=250)))
        print(f"Windows build {windows_build()}, {args.seconds:g} s per mode")
        print(f"{'mode':6} {'delivered/s':>12} {'used/s':>8} {'cpu %':>7} {'cpu ms/frame':>13}")
        for name, run in modes:
            r = measure(name, args.seconds, run)
            print(f"{r['mode']:6} {r['delivered/s']:12.1f} {r['used/s']:8.1f} {r['cpu %']:7.1f} "
                  f"{r['cpu ms/frame']:13.2f}", flush=True)  # fmt: skip
    finally:
        target.kill()


if __name__ == "__main__":
    main()
