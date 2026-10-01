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
- 2026-09-30 — OCR engine: **RapidOCR on the 2× upscaled chat box** (99.8 % chars, 98 % names on 8 hand-checked crops) beats Windows OCR (best 88.6 % / 76 %, loses lines on bright or faded backgrounds). Windows OCR stays as the fallback setting; it is ~10× faster. RapidOCR costs ~590 ms per box on one core, so M2 must OCR changed rows only (#11, #17).
- 2026-09-30 — Autostart moved from parked into M2 (#45); new: me & my crew (#74), capture health + gap records (#75), first-start wizard (#76), spicy yaps (#77). Void runs their own instance; cross-instance sharing is v2.
- 2026-09-30 — Issue hygiene: tick the "Done when" boxes and post a closing comment before an issue closes; unexplained open boxes block closing.
- 2026-09-30 — Milestone boundaries don't stop work: leftover `human` issues move to the next milestone, the milestone closes, work continues.
- 2026-09-30 — `MILESTONE` = the milestone being worked on: M0 and M1 are closed, so releases are `v0.2.x` from now on (the last `v0.0.x` is `v0.0.44`).
- 2026-09-30 — Skip unchanged frames by a *text mask* (thin bright strokes with a dark outline, letter-sized blobs, steady for 2 frames), per line band; only new text pixels count. On a real 2-min slice: 89 % of frames skipped, every new chat line caught within 0.25 s (#17).
- 2026-10-01 — Match start = hero-select banner `ASSEMBLE YOUR TEAM` (top left, whole-text fuzzy match, recognition-only OCR on a 1-line strip ≈ 0.4 % of a core); mode + map read once from the corner; `PREPARE TO …` only as backup when no match runs. On a real 23-min recording: exactly the 2 matches, no false starts (#93).
- 2026-10-01 — Match end = the centre `VICTORY!` / `DEFEAT` banner (colour check, then a 1-line read; gives the outcome); `PLAY OF THE GAME`, `VICTORY <MAP>` and the summary tabs (top left) are the fallbacks. The `[ATHENA]` subtitle is **not** read: subtitles are an optional game setting, the box is multi-line (needs full OCR, more than the whole 1 % budget), and the banner shows 1–2 s later anyway. Post-game chat stays with the match until 90 s of quiet. Real recording: both ends found at the banner second, 0.23 % of a core (#94).
- 2026-10-01 — Dedup (#18): a frame's lines are aligned *in order* with the last 40 lines (fuzzy LCS on "speaker: text"); only unmatched lines below the last match are new. Lines fade ~9 s after they appear, so an older line only matches next to a matched neighbour or in an opened chat. Best reading = read most often, then most confident; trailing all-caps map text glued to a line is ignored for matching. Real 4-min replay: 14 lines out, each once, 0.04 ms per frame. Fallback (exact match within 30 s) not needed.
- 2026-10-01 — Debug samples (#63): an overview frame (every 4th pixel) comes with the signal crops every 5 s; the last 6 min stay in memory as JPEGs, so a missed end screen can be saved when the *next* match starts. Samples: `debug/<date>/<time>-start|end|missed-end/`. On by default only in v0.x; 14 days / 1 GB, oldest first; nothing buffered while paused. Chat samples follow in #110.
