"""Release notes (#239): the PR's "What you can see now", or a "Behind the scenes" line."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "tools" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)
notes, whats_new = release_notes.notes, release_notes.whats_new

BODY = """## What you can see now
- Chat lines can be fixed or deleted right in the chat, with Undo.
- The window behaves at half-screen width.
  ```
  Pushing the payload  [====>-----]
  ```

## Done when (copied from the issue, same ticks)
- [x] something
"""
PR = {"number": 242, "title": "Edit toggles (#241)", "body": BODY,
      "html_url": "https://github.com/o/r/pull/242"}  # fmt: skip


def test_the_prs_own_words_with_update_and_links():
    text = notes(PR, "o/r", "v0.5.260", "v0.5.259", "")
    assert text.startswith("### What's new\n- Chat lines can be fixed or deleted right in the chat")
    assert "Pushing the payload" in text  # code blocks stay
    assert "Done when" not in text  # developer details stay out
    assert "Update: run `tools/update.ps1`" in text
    compare = "https://github.com/o/r/compare/v0.5.259...v0.5.260"
    links = f"[#242](https://github.com/o/r/pull/242) · [All changes since v0.5.259]({compare})"
    assert text.rstrip().endswith(links)


def test_nothing_to_see_gets_a_behind_the_scenes_line():
    empty = {**PR, "body": "## What you can see now\n- \n\n## Done when\n- [x] a\n"}
    assert "- Behind the scenes: Edit toggles\n" in notes(empty, "o/r", "v2", "v1", "")
    no_section = {**PR, "body": "Tests only."}
    assert "- Behind the scenes: Edit toggles\n" in notes(no_section, "o/r", "v2", "v1", "")


def test_a_commit_without_a_pr_and_the_first_release():
    text = notes(
        None, "o/r", "v0.0.1", None, "DoD: GPU OCR is out of v1 after the real test (#219)"
    )
    assert "- Behind the scenes: DoD: GPU OCR is out of v1 after the real test\n" in text
    assert "compare" not in text


def test_template_comments_dont_count():
    assert whats_new("## What you can see now\n<!-- what users notice -->\n- \n") == ""


def test_command_line(tmp_path):
    pr = tmp_path / "pr.json"
    pr.write_text(json.dumps(PR), encoding="utf-8")
    base = [sys.executable, str(SCRIPT), "--pr", str(pr), "--repo", "o/r", "--tag", "v2"]
    out = subprocess.run([*base, "--previous", "v1"], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("### What's new\n- Chat lines")
    pr.write_text("null", encoding="utf-8")
    out = subprocess.run([*base, "--subject", "Fix a typo"], capture_output=True, text=True,
                         check=True)  # fmt: skip
    assert "- Behind the scenes: Fix a typo" in out.stdout
