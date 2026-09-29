# Decisions & dead ends

One line each, newest at the bottom. Link the issue.

- 2026-09-28 — Scope locked to v1 as written in `CLAUDE.md`; everything else is `parked`. Full lobby rosters stay OverLooker's job.
- 2026-09-28 — Stack: Python 3.12, NiceGUI (native), windows-capture (WGC), RapidOCR, rapidfuzz, SQLite + FTS5, PyInstaller in GitHub Actions.
- 2026-09-28 — Repo is public → real screenshots/chat logs live only in `fixtures/private/` (gitignored).
- 2026-09-29 — UI direction: "simple layout, Overwatch energy, slightly silly". Spec in `docs/ui.md`, mockups in `docs/ui/mockup/`. Replaces the earlier OverLooker-style amber/Inter look.
- 2026-09-29 — No OBS/recording needed: the app captures the chat region itself (WGC), frames are discarded after OCR, only text is stored.
- 2026-09-29 — Matches are detected automatically from the screen (chat join line → end-screen OCR → time gap), hotkey only as override (#21). No Overwolf.
- 2026-09-29 — Zero-touch is a v1 requirement: capture starts with Overwatch, matches auto-detected, pause auto-resumes (#16, #20, #21 labelled `priority`).
