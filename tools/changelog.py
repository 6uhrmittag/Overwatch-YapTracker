"""Changelog fragments (#494): each PR adds changes/<issue>.md instead of editing CHANGELOG.md,
so two PRs in a row never conflict over it. A fragment is the PR's "What you can see now":

    ### Faster checks on every change (#493)
    - Behind the scenes: the automatic checks run in about half the time.

After a merge, CI's pre-release job puts them into CHANGELOG.md (newest first, under the date,
in the open version's section) and deletes them:

    python tools/changelog.py --date 2026-11-07

The release notes still come from the merged PR (tools/release_notes.py), as before.
"""

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGES = "changes"
SKIP = {"README.md"}  # the folder's own explanation


def fragments(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.md") if p.name not in SKIP)


def entry(text: str, date: str, name: str = "fragment") -> str:
    """One fragment as a CHANGELOG entry: "### <date> · <title>" and its bullets."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if not lines or not lines[0].startswith("### ") or len(lines[0]) <= 4:
        raise ValueError(f"{name}: the first line must be '### <title> (#<issue>)'")
    bullets = [line for line in lines[1:] if line]
    if not bullets or not all(line.startswith(("- ", "  ")) for line in bullets):
        raise ValueError(f"{name}: below the title, only '- ' bullets")
    return "\n".join([f"### {date} · {lines[0][4:].strip()}", *bullets])


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


def _added(path: Path) -> int:
    """When the fragment came into the repo (its newest commit): orders the entries."""
    out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", path.name], cwd=path.parent,
                         capture_output=True, text=True, check=False).stdout.strip()  # fmt: skip
    return int(out or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="the merge day, e.g. 2026-11-07")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    found = sorted(fragments(root / CHANGES), key=lambda p: (_added(p), p.name), reverse=True)
    if not found:
        print("no changelog fragments")
        return
    entries = [entry(p.read_text(encoding="utf-8"), args.date, p.name) for p in found]
    changelog = root / "CHANGELOG.md"
    text = assemble(changelog.read_text(encoding="utf-8"), entries)
    changelog.write_text(text, encoding="utf-8", newline="\n")
    for p in found:
        p.unlink()
    print(f"CHANGELOG.md: {', '.join(p.name for p in found)}")


if __name__ == "__main__":
    main()
