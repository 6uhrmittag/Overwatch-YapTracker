"""Command line entry point: `python -m yaptracker`."""

import argparse

from yaptracker import __version__


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
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    # Imported here so `--version` stays instant and works without the UI stack.
    from yaptracker import app

    app.run(dev=args.dev)


if __name__ == "__main__":
    main()
