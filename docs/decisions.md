# Decisions & dead ends

One line each, newest at the bottom. Link the issue.

- 2026-09-28 — Scope locked to v1 as written in `CLAUDE.md`; everything else is `parked`. Full lobby rosters stay OverLooker's job.
- 2026-09-28 — Stack: Python 3.12, NiceGUI (native), windows-capture (WGC), RapidOCR, rapidfuzz, SQLite + FTS5, PyInstaller in GitHub Actions.
- 2026-09-28 — Repo is public → real screenshots/chat logs live only in `fixtures/private/` (gitignored).
- 2026-09-29 — UI direction: "simple layout, Overwatch energy, slightly silly". Spec in `docs/ui.md`, mockups in `docs/ui/mockup/`. Replaces the earlier OverLooker-style amber/Inter look.
- 2026-09-29 — No OBS/recording needed: the app captures the chat region itself (WGC), frames are discarded after OCR, only text is stored.
- 2026-09-29 — Matches are detected automatically from the screen (chat join line → end-screen OCR → time gap), hotkey only as override (#21). No Overwolf.
- 2026-09-29 — Zero-touch is a v1 requirement: capture starts with Overwatch, matches auto-detected, pause auto-resumes (#16, #20, #21 labelled `priority`).
- 2026-09-29 — Development happens in WSL; Windows-only parts sit behind interfaces with fakes and are verified via CI builds. `--dev` browser mode for instant UI review.
- 2026-09-29 — Versions: `v0.<milestone>.<run_number>` from `MILESTONE` in `.github/workflows/ci.yml` (bump it when closing a milestone); PR builds are `...+pr<N>` and never released (#5).
- 2026-09-29 — Real screenshots reviewed (#7, #8): brackets wrap names not channels, channel = icon + colour, team colour is user-configurable (green here). Match start = hero-select screen (no "joined match chat" line exists); map/mode/hero stored when read (#13, #21).
- 2026-09-29 — Full OBS match recordings are the main replay material; frames are extracted by a script, recordings stay on Windows, nothing committed.
- 2026-09-30 — The app collects its own debug samples (hard OCR frames, match-signal frames) from M2 on, so manual screenshot collection stops (#63).
- 2026-09-30 — Yap snaps (chat messages → styled PNG) added to M4, built on the transcript view; style controls are the parkable part (#64, #65).
- 2026-09-30 — Full open-data export (JSON + Markdown, documented schema, optional anonymized names) in M4; README states the code is written by AI (#69).
