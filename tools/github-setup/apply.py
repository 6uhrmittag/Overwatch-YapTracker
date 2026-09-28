"""Create labels, milestones, issues and the pinned roadmap from backlog.py.

Idempotent: existing labels/milestones/issues (matched by name/title) are reused.
Usage:  GH_TOKEN=... python tools/github-setup/apply.py [owner/repo]
        (falls back to `gh auth token` if GH_TOKEN is not set)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import backlog  # noqa: E402

REPO = sys.argv[1] if len(sys.argv) > 1 else "6uhrmittag/Overwatch-YapTracker"
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or subprocess.run(
    ["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
API = "https://api.github.com"


def call(method, path, data=None, ok=(200, 201, 204)):
    url = path if path.startswith("http") else f"{API}{path}"
    req = urllib.request.Request(url, method=method, data=json.dumps(data).encode() if data is not None else None)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 4 and "rate limit" in e.read().decode().lower():
                time.sleep(30)
                continue
            if e.code == 404 and method == "DELETE":
                return None
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:300]}") from e


def paged(path):
    out, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = call("GET", f"{path}{sep}per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def main():
    r = f"/repos/{REPO}"

    # Labels
    existing = {lbl["name"]: lbl for lbl in paged(f"{r}/labels")}
    for name in backlog.DELETE_LABELS:
        if name in existing:
            call("DELETE", f"{r}/labels/{urllib.parse.quote(name)}")
    for name, colour, desc in backlog.LABELS:
        payload = {"name": name, "color": colour, "description": desc}
        if name in existing:
            call("PATCH", f"{r}/labels/{urllib.parse.quote(name)}", payload)
        else:
            call("POST", f"{r}/labels", payload)
    print(f"labels: {len(backlog.LABELS)}")

    # Milestones
    ms = {m["title"]: m["number"] for m in paged(f"{r}/milestones?state=all")}
    ms_numbers = []
    for title, desc in backlog.MILESTONES:
        if title not in ms:
            ms[title] = call("POST", f"{r}/milestones", {"title": title, "description": desc})["number"]
        ms_numbers.append(ms[title])
    print(f"milestones: {len(ms_numbers)}")

    # Issues (pass 1: create)
    have = {i["title"]: i["number"] for i in paged(f"{r}/issues?state=all") if "pull_request" not in i}
    numbers = {}
    for key, m_idx, labels, title, text in backlog.ISSUES:
        if title in have:
            numbers[key] = have[title]
            continue
        payload = {"title": title, "body": text, "labels": labels}
        if m_idx is not None:
            payload["milestone"] = ms_numbers[m_idx]
        numbers[key] = call("POST", f"{r}/issues", payload)["number"]
        print(f"  #{numbers[key]} {title}")
        time.sleep(1)  # be gentle with the secondary rate limit

    # Pass 2: resolve {{#key}} placeholders
    for key, _, _, title, text in backlog.ISSUES:
        if "{{#" in text:
            resolved = re.sub(r"\{\{#([\w-]+)\}\}", lambda m: f"#{numbers[m.group(1)]}", text)
            call("PATCH", f"{r}/issues/{numbers[key]}", {"body": resolved})

    # Roadmap
    lines = ["Everything for **v1** is below. Work top to bottom; one milestone at a time.",
             "",
             "- 🟣 `human` = Marv/Void do it · 🟢 `quick-win` = one match · ⭐ = the heart of the app",
             "- New ideas → an issue with `parked`. Not now. 🅿️",
             f"- Rules for Claude Code: see [`CLAUDE.md`](https://github.com/{REPO}/blob/main/CLAUDE.md)", ""]
    for idx, (mtitle, mdesc) in enumerate(backlog.MILESTONES):
        lines += [f"### {mtitle}", f"_{mdesc}_", ""]
        for key, m_idx, labels, title, _ in backlog.ISSUES:
            if m_idx == idx:
                tag = " 🟣" if "human" in labels else (" 🟢" if "quick-win" in labels else "")
                lines.append(f"- [ ] #{numbers[key]}{tag}")
        lines.append("")
    parked = [f"#{numbers[k]}" for k, m, *_ in backlog.ISSUES if m is None]
    lines += ["### 🅿️ Parked (not v1)", " ".join(parked), "",
              "**v1 is done when M5 is closed. Then we stop. 🎉**"]
    roadmap_body = "\n".join(lines)
    if backlog.ROADMAP_TITLE in have:
        roadmap = have[backlog.ROADMAP_TITLE]
        call("PATCH", f"{r}/issues/{roadmap}", {"body": roadmap_body})
    else:
        roadmap = call("POST", f"{r}/issues", {"title": backlog.ROADMAP_TITLE, "body": roadmap_body})["number"]
    print(f"roadmap: #{roadmap}")

    # Pin the roadmap (GraphQL)
    node = call("GET", f"{r}/issues/{roadmap}")["node_id"]
    try:
        call("POST", f"{API}/graphql", {"query": "mutation($id:ID!){pinIssue(input:{issueId:$id}){issue{number}}}",
                                        "variables": {"id": node}})
        print("roadmap pinned")
    except RuntimeError as e:
        print(f"pin skipped: {e}")


if __name__ == "__main__":
    main()
