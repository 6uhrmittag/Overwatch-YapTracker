"""Release notes for a pre-release (#239): what the merged PR says under "What you can see now"
(user-facing, in the app's own words), then how to update, the PR and the compare link.
CI's release job runs it; one merge to main is one release.

    python tools/release_notes.py --pr pr.json --repo owner/name --tag v0.5.250 \\
        --previous v0.5.249 --subject "commit subject" > notes.md

pr.json: GitHub's pull request of the release commit ({"number", "title", "body", "html_url"}),
or null for a commit pushed without a PR.

A stable release (#454) is a tested pre-release published again, the same zip. Its notes gather
the bullets of every pre-release since the last stable one and name the build it is:

    python tools/release_notes.py --stable 1.1.0 --from v1.1.0-pre.512 \
        --releases releases.json --repo owner/name > notes.md
"""

import argparse
import json
import re
from pathlib import Path

_SECTION = re.compile(r"^##\s+What you can see now\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
UPDATE = "Update: run `tools/update.ps1`, your data stays where it is."


def whats_new(body: str | None) -> str:
    """The PR's "What you can see now" section, or "" when it's missing or still the template."""
    found = _SECTION.search(body or "")
    if not found:
        return ""
    text = _COMMENT.sub("", found.group(1)).strip()
    if not re.sub(r"[\s\-*]", "", text):  # only the template's empty "- "
        return ""
    return text


def notes(pr: dict | None, repo: str, tag: str, previous: str | None, subject: str) -> str:
    title = (pr or {}).get("title") or subject
    title = re.sub(r"\s*\(#\d+\)$", "", title.strip())  # "(#238)": the issue, linked below
    new = whats_new((pr or {}).get("body"))
    lines = ["### What's new", new or f"- Behind the scenes: {title}", "", UPDATE, ""]
    links = []
    if pr:
        links.append(f"[#{pr['number']}]({pr['html_url']})")
    if previous:
        links.append(f"[All changes since {previous}](https://github.com/{repo}/compare/"
                     f"{previous}...{tag})")  # fmt: skip
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines).rstrip() + "\n"


def _version(tag: str | None) -> tuple | None:
    """Like yaptracker.updates.version: "v1.1.0-pre.5" comes before "v1.1.0"."""
    found = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-pre\.(\d+))?", tag or "")
    if not found:
        return None
    return int(found[1]), int(found[2]), int(found[3]), 0 if found[4] else 1, int(found[4] or 0)


def stable_notes(releases: list[dict], build: str, stable: str, repo: str) -> str:
    """What's new in a stable release: the bullets of the pre-releases since the last stable one
    up to the build, newest first, repeats once, "behind the scenes" counted. The last line says
    which build it is: the app and update.ps1 take that build as up to date with it."""
    mine = _version(build)
    listed = [r for r in releases if not r.get("draft") and _version(r.get("tag_name"))]
    before = [r for r in listed if not r.get("prerelease") and _version(r["tag_name"]) < mine]
    last = max(before, key=lambda r: _version(r["tag_name"]), default=None)
    since = _version(last["tag_name"]) if last else None
    included = sorted((r for r in listed if r.get("prerelease") and _version(r["tag_name"]) <= mine
                       and (since is None or _version(r["tag_name"]) > since)),
                      key=lambda r: _version(r["tag_name"]), reverse=True)  # fmt: skip
    bullets, behind = [], 0
    for release in included:
        for line in (release.get("body") or "").splitlines():
            if not line.startswith("- "):
                continue
            if line.startswith("- Behind the scenes"):
                behind += 1
            elif line not in bullets:
                bullets.append(line)
    if behind:
        bullets.append(f"- (+ {behind} behind-the-scenes change{'s' if behind != 1 else ''})")
    lines = ["### What's new", *(bullets or ["- Behind the scenes: small fixes."]), "", UPDATE, ""]
    links = [f"Same build as {build}"]
    if last:
        links.append(f"[All changes since {last['tag_name']}](https://github.com/{repo}/compare/"
                     f"{last['tag_name']}...{build})")  # fmt: skip
    lines.append(" · ".join(links))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", help="JSON file: the PR, or null")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--previous", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--stable", help="a stable release's version, e.g. 1.1.0 (#454)")
    parser.add_argument("--from", dest="build", help="the pre-release it is, e.g. v1.1.0-pre.512")
    parser.add_argument("--releases", help="JSON file: GitHub's release list")
    args = parser.parse_args()
    if args.stable:
        releases = json.loads(Path(args.releases).read_text(encoding="utf-8"))
        print(stable_notes(releases, args.build, args.stable, args.repo), end="")
        return
    # A commit without a PR: gh prints an empty line for `.[0] // null` (#398).
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8").strip() or "null")
    print(notes(pr, args.repo, args.tag, args.previous or None, args.subject), end="")


if __name__ == "__main__":
    main()
