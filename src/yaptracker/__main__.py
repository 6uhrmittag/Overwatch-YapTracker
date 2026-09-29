"""Command line entry point: `python -m yaptracker`."""

import argparse

from yaptracker import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yaptracker", description="Overwatch chat & player memory"
    )
    parser.add_argument("--version", action="version", version=f"YapTracker {__version__}")
    return parser


def main(argv: list[str] | None = None) -> None:
    build_parser().parse_args(argv)


if __name__ == "__main__":
    main()
