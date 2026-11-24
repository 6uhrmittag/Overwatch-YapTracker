"""Command line entry point: `python -m yaptracker` and the packaged YapTracker.exe."""

import argparse
import json
import multiprocessing
import multiprocessing.spawn
import sys

from yaptracker import __version__, logs


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


def reader_has_its_own_process(dev: bool) -> bool:
    """As app.py decides it (#563): not in --dev, not with "ocr_own_process": false. Read here
    with plain json: the config module pulls in the image stack, and a second start mustn't
    touch (or rename) the running one's config."""
    if dev:
        return False
    try:
        from yaptracker import paths

        with open(paths.config_file(), encoding="utf-8") as file:
            return json.load(file).get("ocr_own_process", True) is not False
    except (OSError, ValueError, AttributeError):  # none yet, or unreadable: the default
        return True


def main(argv: list[str] | None = None) -> None:
    logs.setup()  # also catches stdout/stderr: the windowed exe has no console
    from yaptracker import priority

    # The game goes first (#187): below normal priority for every process of ours. The child
    # processes (the window, the chat reader's OCR) also run in Windows' efficiency mode; in
    # the exe a child starts right here and never gets past freeze_support().
    if multiprocessing.spawn.is_forking(sys.argv):
        priority.lower_process()
    multiprocessing.freeze_support()
    args = build_parser().parse_args(argv)  # --version ends here: instant
    # The main process is in efficiency mode only when it reads the chat itself (#563): with
    # the reader in its own process it needs little CPU, but on time.
    priority.lower_process(efficiency=not reader_has_its_own_process(args.dev))
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
