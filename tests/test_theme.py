import re
from pathlib import Path

THEME = Path(__file__).parents[1] / "src" / "yaptracker" / "ui" / "static" / "theme.css"


def test_hidden_beats_every_component_that_sets_display():
    # .yt-banner / .yt-chip set their own display later in the file; without !important they
    # win and "hidden" elements show up empty (#95).
    rule = re.search(r"\.yt-hidden\s*\{([^}]*)\}", THEME.read_text()).group(1)
    assert re.search(r"display:\s*none\s*!important", rule)


def test_dialog_cards_take_clicks():
    """#200: Quasar only enables div children of a dialog; ours are <section> cards."""
    assert re.search(
        r"\.q-dialog__inner\s*>\s*\*\s*\{[^}]*pointer-events:\s*all", THEME.read_text()
    )
