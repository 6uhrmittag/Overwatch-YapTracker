"""Release notes for a pre-release (#239): what the merged PR says under "What you can see now"
(user-facing, in the app's own words), then how to update, the PR and the compare link.
CI's release job runs it; one merge to main is one release.

    python tools/release_notes.py --pr pr.json --repo owner/name --tag v0.5.250 \\
        --previous v0.5.249 --subject "commit subject" > notes.md

pr.json: GitHub's pull request of the release commit ({"number", "title", "body", "html_url"}),
or null for a commit pushed without a PR.
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", required=True, help="JSON file: the PR, or null")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--previous", default="")
    parser.add_argument("--subject", default="")
    args = parser.parse_args()
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8") or "null")
    print(notes(pr, args.repo, args.tag, args.previous or None, args.subject), end="")


if __name__ == "__main__":
    main()
