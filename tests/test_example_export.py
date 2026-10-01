"""The example export in examples/export/ (#160) matches the schema and is up to date."""

import importlib.util
import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "export"


def test_the_example_matches_the_published_schema():
    schema = json.loads((ROOT / "docs" / "export.schema.json").read_text(encoding="utf-8"))
    example = json.loads((EXAMPLE / "yaptracker-export.json").read_text(encoding="utf-8"))
    jsonschema.validate(example, schema)
    assert "examples/export" in (ROOT / "docs" / "export-format.md").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="time.tzset is Unix only")
def test_the_example_is_what_the_tool_makes_today(tmp_path):
    """Changed the export format? Run `python tools/make_example_export.py` and commit."""
    spec = importlib.util.spec_from_file_location("make_example", ROOT / "tools" /
                                                  "make_example_export.py")  # fmt: skip
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    tool.make(tmp_path / "export")
    made = {p.relative_to(tmp_path / "export"): p.read_text(encoding="utf-8")
            for p in (tmp_path / "export").rglob("*") if p.is_file()}  # fmt: skip
    committed = {p.relative_to(EXAMPLE): p.read_text(encoding="utf-8")
                 for p in EXAMPLE.rglob("*") if p.is_file()}  # fmt: skip
    assert made == committed
