"""Changelog fragments (#494): each PR adds changes/<issue>.md instead of editing CHANGELOG.md,
so two PRs in a row never conflict over it. A fragment is the PR's "What you can see now":

    ### Faster checks on every change (#493)
    - Behind the scenes: the automatic checks run in about half the time.

A second PR for the same issue names its file changes/<issue>-2.md. After a merge, CI's
pre-release job puts them into CHANGELOG.md (newest first, on top of the first "## " section,
dated the day they were merged) and deletes them:

    python tools/changelog.py

The release notes still come from the merged PR (tools/release_notes.py), as before.
"""

import argparse
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CHANGES = "changes"
SKIP = {"README.md"}  # the folder's own explanation
NAME = re.compile(r"^(\d+)(?:-\d+)?\.md$")  # 493.md, 493-2.md
TITLE = re.compile(r"^### (?P<title>\S.*\(#(?P<issue>\d+)\))$")
LOCAL = ZoneInfo("Europe/Berlin")  # the day as Marv and Void lived it, like the older entries


def fragments(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.md") if p.name not in SKIP)


def entry(text: str, date: str, name: str = "1.md") -> str:
    """One fragment as a CHANGELOG entry: "### <date> · <title> (#N)" and its bullets."""
    named = NAME.match(name)
    if not named:
        raise ValueError(f"{name}: name it changes/<issue>.md (or <issue>-2.md)")
    lines = [line.rstrip() for line in text.strip().splitlines()]
    title = TITLE.match(lines[0]) if lines else None
    if not title:
        raise ValueError(f"{name}: the first line must be '### <title> (#<issue>)'")
    if title["issue"] != named[1]:
        raise ValueError(f"{name}: the title says #{title['issue']}, the file name #{named[1]}")
    bullets = [line for line in lines[1:] if line]
    if not bullets or not bullets[0].startswith("- "):
        raise ValueError(f"{name}: below the title, '- ' bullets")
    if not all(line.startswith(("- ", "  ")) for line in bullets):
        raise ValueError(f"{name}: below the title, only '- ' bullets (and their indented lines)")
    return "\n".join([f"### {date} · {title['title']}", *bullets])


def assemble(changelog: str, entries: list[str]) -> str:
    """The entries (newest first) on top of the first "## " section, the open version's."""
    if not entries:
        return changelog
    lines = changelog.splitlines(keepends=True)
    at = next((i for i, line in enumerate(lines) if line.startswith("## ")), None)
    if at is None:
        raise ValueError("CHANGELOG.md has no '## ' section to add to")
    at += 1
    while at < len(lines) and not lines[at].strip():
        at += 1
    block = "\n\n".join(entries) + "\n\n"
    return "".join(lines[:at]) + block + "".join(lines[at:])


def merged_at(path: Path) -> int:
    """When the fragment came into main (its newest commit); 0 if git doesn't know."""
    out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", path.name], cwd=path.parent,
                         capture_output=True, text=True, check=False).stdout.strip()  # fmt: skip
    return int(out or 0)


def day(ts: int) -> str:
    return datetime.fromtimestamp(ts or time.time(), LOCAL).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    found = [(merged_at(p), int(NAME.match(p.name)[1]) if NAME.match(p.name) else 0, p)
             for p in fragments(root / CHANGES)]  # fmt: skip
    found.sort(key=lambda f: (f[0], f[1], f[2].name), reverse=True)  # newest first
    if not found:
        print("no changelog fragments")
        return
    entries = [entry(p.read_text(encoding="utf-8"), day(ts), p.name) for ts, _, p in found]
    changelog = root / "CHANGELOG.md"
    text = assemble(changelog.read_text(encoding="utf-8"), entries)
    changelog.write_text(text, encoding="utf-8", newline="\n")
    for _, _, p in found:
        p.unlink()
    print(f"CHANGELOG.md: {', '.join(p.name for _, _, p in found)}")


if __name__ == "__main__":
    main()
