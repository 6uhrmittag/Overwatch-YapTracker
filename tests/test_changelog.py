"""Changelog fragments (#494): changes/<issue>.md -> CHANGELOG.md after the merge."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools" / "changelog.py"
_spec = importlib.util.spec_from_file_location("changelog", SCRIPT)
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

LOG = """# Changelog

Intro.

## v1.1: on the way to v1.1.0

### 2026-11-06 · Older (#1)
- Old bullet.

## v1.0.0
"""


def test_entry_gets_the_date():
    text = "### Faster checks (#493)\n- Behind the scenes: quicker.\n"
    assert changelog.entry(text, "2026-11-07") == (
        "### 2026-11-07 · Faster checks (#493)\n- Behind the scenes: quicker."
    )


@pytest.mark.parametrize("bad", ["", "- no title\n", "### \n- x", "### T (#1)\n", "### T\nprose"])
def test_a_broken_fragment_says_so(bad):
    with pytest.raises(ValueError):
        changelog.entry(bad, "2026-11-07", "1.md")


def test_entries_go_on_top_of_the_open_version():
    entries = ["### 2026-11-07 · New (#3)\n- Three.", "### 2026-11-07 · Mid (#2)\n- Two."]
    out = changelog.assemble(LOG, entries)
    assert out.index("New (#3)") < out.index("Mid (#2)") < out.index("Older (#1)")
    assert "## v1.1: on the way to v1.1.0\n\n### 2026-11-07 · New (#3)\n- Three.\n\n" in out
    assert "- Two.\n\n### 2026-11-06" in out
    assert changelog.assemble(LOG, []) == LOG


def test_the_script_writes_and_deletes(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(LOG, encoding="utf-8")
    changes = tmp_path / "changes"
    changes.mkdir()
    (changes / "README.md").write_text("How fragments work.\n", encoding="utf-8")
    (changes / "7.md").write_text("### Seven (#7)\n- A bullet.\n", encoding="utf-8")
    subprocess.run([sys.executable, str(SCRIPT), "--date", "2026-11-08", "--root", str(tmp_path)],
                   check=True, capture_output=True)  # fmt: skip
    text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "### 2026-11-08 · Seven (#7)\n- A bullet.\n\n### 2026-11-06" in text
    assert [p.name for p in changes.iterdir()] == ["README.md"]


def test_every_fragment_in_the_repo_is_well_formed():
    """Caught in the PR, not after the merge when the pre-release job puts them together."""
    for path in changelog.fragments(ROOT / "changes"):
        changelog.entry(path.read_text(encoding="utf-8"), "2026-01-01", path.name)
