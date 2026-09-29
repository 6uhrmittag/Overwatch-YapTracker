"""Start the NiceGUI app: native window on Windows, browser mode with --dev."""

from nicegui import app, ui

from yaptracker.ui import shell

TITLE = "YapTracker"
WINDOW_SIZE = (1280, 800)
DEV_HOST = "0.0.0.0"
DEV_PORT = 8080


def run(*, dev: bool = False) -> None:
    shell.register_static_files()
    common = {
        "title": TITLE,
        "favicon": shell.STATIC_DIR / "logo.svg",
        "dark": True,
        "reload": False,
        "show_welcome_message": dev,
    }
    if dev:
        ui.run(shell.root, host=DEV_HOST, port=DEV_PORT, show=False, **common)
    else:
        # Paint the native window in the night colour before the page loads - no white flash.
        app.native.window_args["background_color"] = "#0d1016"
        ui.run(shell.root, native=True, window_size=WINDOW_SIZE, **common)
