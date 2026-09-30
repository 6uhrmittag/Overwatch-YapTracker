"""Command line entry point: `python -m yaptracker` and the packaged YapTracker.exe."""

import argparse
import multiprocessing
import sys

from yaptracker import __version__, paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yaptracker", description="Overwatch chat & player memory"
    )
    parser.add_argument("--version", action="version", version=f"YapTracker {__version__}")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="browser mode on http://localhost:8080 instead of the native window",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="open the window, exit 0 once the page has loaded (used by CI)",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="start minimised and wait for Overwatch (used by Start with Windows)",
    )
    parser.add_argument(
        "--autostart",
        choices=["on", "off"],
        help="answer to update.ps1's first-install question 'Start with Windows?'",
    )
    return parser


def _log_to_file_without_console() -> None:
    """The windowed exe has no console, so stdout/stderr are None. Send them to the log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = paths.log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def main(argv: list[str] | None = None) -> None:
    _log_to_file_without_console()
    # The native window runs in a spawned child process; in the exe that child starts here.
    multiprocessing.freeze_support()
    args = build_parser().parse_args(argv)
    if sys.platform == "win32" and not (args.dev or args.smoke_test):
        from yaptracker import single_instance

        if not single_instance.acquire():
            single_instance.bring_running_to_front()
            return
    # Imported here so `--version` stays instant and works without the UI stack.
    from yaptracker import app

    app.run(
        dev=args.dev,
        smoke_test=args.smoke_test,
        background=args.background,
        autostart=None if args.autostart is None else args.autostart == "on",
    )


if __name__ == "__main__":
    main()
