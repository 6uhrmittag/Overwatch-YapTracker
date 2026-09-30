# YapTracker — Overwatch chat & player memory

Repo: https://github.com/6uhrmittag/Overwatch-YapTracker (public)
Handover brief for Claude Code. You are starting cold; everything you need is here.

---

## Why this exists

Marv and his duo partner Void play Overwatch together after work and have a lot of
fun with people in text chat. They want to **remember who they played with, what
those people said, and what they thought of them** — so they can greet them next
time ("hey, you're the Lúcio from Tuesday!").

YapTracker reads Overwatch's chat box from the screen (OCR), logs every message
locally, and lets them keep notes and verdicts on players. That's it.

Match stats and full lobby rosters are **not** our job — OverLooker (a separate,
already-installed tracker) covers those.

---

## How we work — read this before writing any code

This project **must ship**. The user's history: projects reach 90% and stall.
The rules below exist to prevent exactly that. They override your instincts.

### The user is playing while you work
Marv codes on this *during* Overwatch sessions. You work while a match runs
(~10 min); he reviews while the queue searches (~1–3 min). If nothing usable
appears quickly, the session is lost and so is momentum.

1. **Match-sized increments.** Every unit of work is one GitHub issue → one PR
   with **one visible outcome**, reviewable in under 2 minutes. Aim for
   ≤ ~300 changed lines. If an issue is bigger, split it before starting.
2. **Always deliver something.** Keep 3–5 small, ready issues in the current
   milestone at all times, so there is always a next quick win.
3. **Don't block on the user.** Don't ask mid-task. Make the reasonable call,
   note it in the PR under "Decisions I made", and continue. Only stop to ask
   for irreversible choices (data model changes once real data exists, deleting
   things). Batch questions into one message/comment.
4. **Don't compete with the game.** No heavy local work while the user plays:
   no local release builds, no model downloads, no benchmarks. CI builds.

### The one-hour rule (blocker protocol)
Interesting problems are the biggest risk. **Timebox every problem to 45 minutes
of effort.** When the timebox runs out:
1. Open (or update) an issue labelled `blocker` with what you tried and found.
2. Switch to the pre-decided fallback from the table below.
3. Move on. Do not return to the original approach in this milestone.

| Risk | Plan A | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Screen capture | WGC **window** capture of `Overwatch.exe` (`windows-capture`) | WGC **monitor** capture + crop | `mss` (GDI) screenshot of the monitor |
| OCR quality | RapidOCR (ONNX, CPU) | Windows.Media.Ocr via `winsdk` | Ship with a "fix text" edit button; PaddleOCR GPU goes to `parked` |
| Native window / packaging | NiceGUI `native=True` + PyInstaller | NiceGUI as local server, opened in an Edge app window (`msedge --app=http://127.0.0.1:<port>`) | Plain browser tab |
| Channel detection (team/match/group) | Parse `[Team]`/`[Match]` prefix + prefix colour | Prefix text only | Store `channel = unknown`, still log the line |
| Duplicate lines | Fuzzy line matching (rapidfuzz) with neighbour context | Exact-match dedup within a 30 s window | Keep duplicates, hide via "collapse repeats" toggle |
| Match detection | Hero-select `ASSEMBLE YOUR TEAM` (start) + VICTORY/DEFEAT/POTG/endorse screen OCR (end) | Time gap (90 s after end, 5 min general) | `Ctrl+Alt+M` hotkey only |
| Speaker → player matching | Fuzzy match against known players + aliases | Exact case-insensitive match | Create new player; manual merge button |

### GitHub is the source of truth
The repo is already set up: milestones M0–M5, labels, the full v1 backlog as
issues, `parked` ideas, and a pinned **🗺️ Roadmap** issue. Use the `gh` CLI.
Don't recreate any of it; `tools/github-setup/` is only the record of how it was
made.

**Picking the next thing to do:**
1. Open milestone = the lowest-numbered one that still has open issues. Never
   work ahead into a later milestone while the current one has open issues
   (except `human` issues you're waiting on — work around those).
2. In that milestone, skip issues labelled `human`, `parked` or `needs-decision`
   and issues whose "Blocked by" issue is still open.
3. Prefer `priority`, then `quick-win`, then the lowest issue number.
4. Comment "Starting" on the issue, work on a branch `issue-<N>-<slug>`, open a
   PR that `Closes #N`.

**Labels:**
| Label | Meaning |
|---|---|
| `blocker` | Timebox hit; fallback in use. Explains what was tried |
| `bug` | Something that worked is broken |
| `human` | Only Marv/Void can do this (screenshots, play-testing) — don't start it |
| `needs-decision` | Waiting on Marv; put all open questions in one comment |
| `parked` | Good idea, not v1. Never implement without Marv's explicit OK |
| `priority` | Marv asked for this explicitly — do it first as soon as it's unblocked |
| `quick-win` | Fits in one match (~10 min of review-ready work) |
| `spike` | Research with a hard 45 min timebox; outcome = a line in `docs/decisions.md` |
| `ci` | Build, release, update pipeline |
| `ux` | Look & feel polish |
| `area:*` | capture · ocr · parser · storage · players · ui |

- New ideas (yours or Marv's) → new issue with label `parked`, no milestone.
- Bugs found mid-work → new `bug` issue in the current milestone; don't
  silently widen the PR.
- Keep `docs/decisions.md` short: one line per decision or dead end, with issue link.
- When a milestone's issues are all closed: make sure a pre-release exists,
  close the milestone, update the Roadmap issue if needed.

**PR template** (`.github/pull_request_template.md`):
```
## What you can see now
- (1–3 bullets, user-visible)

## Screenshot
(UI changes: screenshot, compared against docs/ui/mockup)

## Test it in 60 seconds
1. Download the artifact / latest pre-release (or run `tools/update.ps1`)
2. ...

## Decisions I made
- ...

Closes #
```

---

## Scope

### v1 — the finish line
1. Capture the chat region, OCR it, dedup, store locally.
2. **Live** view: chat streaming in, and a **familiar-face card** whenever a
   known player speaks (name, verdict, last met, their notes). This is the
   heart of the app — it's what makes greeting people possible.
3. **Quick lookup**: search box with fuzzy name search. Covers players who
   didn't chat (the user reads a name off the scoreboard and types it in).
4. **Players**: verdict (`friend` / `fun` / `neutral` / `avoid`), free-text
   notes (autosave), first/last met, every message they sent, alias list,
   manual "add player" and "merge players".
5. **Sessions**: chat grouped by play session and by match — matches detected
   automatically from the screen (hero-select screen, VICTORY/DEFEAT screen,
   time gap), `Ctrl+Alt+M` as manual override — transcript view.
6. **Search** across all chat (SQLite FTS5).
7. **Settings**: chat-region calibration on a screenshot, OCR engine switch,
   sample rate, hotkeys, data folder, backup button.
8. Players + notes export to Markdown and JSON.

### Not in v1 — already filed as `parked` issues, ignore them
Video/recording import · Overwolf game events · reading OverLooker's files ·
Tab-scoreboard OCR / full rosters · tags · review queue · PaddleOCR GPU ·
installer · autostart · in-app auto-updater · tray icon · statistics/charts ·
sharing notes between Marv's and Void's PCs.

Anything new the user or you think of → a `parked` issue. Moving an issue from
`parked` into a milestone requires the user saying so explicitly.

---

## Milestones

Each milestone should fit in one or two evenings and ends with a working
pre-release.

**M0 — Skeleton & pipeline** *(first, before any OCR)*
- Repo scaffold, `pyproject.toml`, ruff, pytest, `.gitignore` (incl. `fixtures/private/`)
- App opens a dark window with the left nav rail and empty views
- GitHub Actions: tests on every PR; Windows PyInstaller build on every PR
  (uploaded as artifact); on push to `main` → GitHub **pre-release**
  `v0.<milestone>.<run_number>` with the zipped app
- `tools/update.ps1`: downloads the latest (pre-)release, replaces the app
  folder, never touches the data folder
- `human` issues: collect screenshots, check Overwatch chat settings

**M1 — Read a screenshot**
- Chat-region calibration on a screenshot (drag a rectangle)
- OCR + line parsing on a screenshot file → parsed lines shown in the UI
- Accuracy check against private fixtures; pick the OCR engine (timeboxed!)

**M2 — Live chat log** *(first moment of real value)*
- Live capture → change detection → OCR → dedup → SQLite
- **Zero-touch** (`priority`): capture starts/stops with Overwatch, matches and
  sessions are detected automatically, pause auto-resumes at the next match.
  Marv *will* forget to press keys — a normal evening must need none.
- Live view streaming messages; pause hotkey

**M3 — Remember people**
- Players view, notes, verdicts, merge, manual add
- Familiar-face card in Live view; quick lookup with hotkey

**M4 — Browse**
- Sessions/matches with transcripts, full-text search, export

**M5 — v1.0**
- Acceptance session (see Definition of done), README, `v1.0.0` stable release,
  close the milestone. Then stop.

---

## Hard guardrails

Overwatch uses Blizzard's anti-cheat. YapTracker must look, from the game's point
of view, like OBS or the Snipping Tool.

- **Screen capture only.** Never read game memory, inject DLLs, hook
  DirectX/Present, or attach a debugger.
- **No input to the game.** Never send keystrokes/clicks to the Overwatch window.
  Global hotkeys registered by our app (`RegisterHotKey`) are fine.
- **No overlay on the game.** The UI is its own window (second monitor or alt-tab).
- **Local-only.** No telemetry, no cloud, no uploads. Only network call allowed:
  the update script fetching GitHub releases.
- **The repo is public.** Never commit screenshots or real chat logs — they
  contain other players' names. Real samples live in `fixtures/private/`
  (gitignored). Committed test fixtures are OCR-output JSON with names replaced.
- **App and data are separate.** App in `%LOCALAPPDATA%\YapTracker\app`, data in
  `%LOCALAPPDATA%\YapTracker\data`. Back up the DB automatically before any
  schema migration.

---

## Environment

| | |
|---|---|
| OS | Windows 10/11 (PowerShell 5.1 + 7) |
| GPU | RTX 4090 **plus** AMD Ryzen iGPU (hybrid) |
| Monitors | Multi-monitor; YapTracker usually on the second screen |
| Game | Overwatch 2 via Battle.net, **borderless windowed** required for capture |
| User | Experienced IT person, confident "hacking together" coder; wants a finished tool |

Hybrid GPU: DXGI Desktop Duplication (dxcam) often returns black frames when
adapters differ — that's why capture uses WGC. Don't suggest disabling the iGPU.

---

## Stack (decided — don't re-litigate)

- Python 3.12
- UI: **NiceGUI** in native mode (pywebview/WebView2), dark theme
- Capture: `windows-capture` (WGC)
- OCR: `rapidocr-onnxruntime`; Windows OCR via `winsdk` as fallback
- Text matching: `rapidfuzz`
- Storage: SQLite, WAL mode, FTS5
- Hotkeys: `RegisterHotKey` via a small ctypes wrapper
- Build: PyInstaller (one-folder) in GitHub Actions `windows-latest`

**Dev environment:** Claude Code runs in **WSL (Ubuntu)**; the app runs on
**Windows**. So:
- Clone inside the WSL filesystem (Marv: `~/workspace/Overwatch-YapTracker`), never under `/mnt/c` (slow, file-watch issues).
- Everything except capture, hotkeys and packaging is developed and tested in WSL.
- **Quick UI review without a build:** `python -m yaptracker --dev` runs NiceGUI in
  browser mode on `0.0.0.0:8080` with fake data (replay frames + a seeded demo DB).
  Marv opens `http://localhost:8080` in his Windows browser (WSL forwards localhost)
  and reviews during a queue. Mention the command in every UI PR.
- Windows-only parts (WGC capture, `RegisterHotKey`, window focus, PyInstaller)
  are behind interfaces with fakes for WSL, and verified via the CI Windows build /
  pre-release on Marv's PC. Never try to run them in WSL.
- `.ps1` files: ASCII only (Windows PowerShell 5.1 misreads UTF-8 without BOM),
  CRLF via `.gitattributes`.

**Testability rule:** everything except capture must run and be tested on
Linux too. Put capture behind a `FrameSource` interface with a
`ReplayFrameSource` that feeds saved frames — that powers tests, CI and
development without the game running.

---

## Pipeline

```
FrameSource (WGC, ~4 fps, chat ROI only)
  → change detector (skip identical frames; cheap diff/hash)
  → OCR (lines with boxes + confidence)
  → parser (channel, speaker, text; system lines → channel=system)
  → dedup (fuzzy vs recent lines, neighbour context; keep best reading)
  → player matcher (fuzzy vs players + aliases)
  → store (SQLite) → UI updates
```

**Chat line formats — verified on real 2560×1440 screenshots (details: #13):**

| Kind | Leading icon | Shape |
|---|---|---|
| Match chat | ◆ diamond (orange) | `[Name]: text` |
| Team chat | team icon (green = friendly colour) | `[Name]: text` |
| Team comms wheel | team icon | `Name (Hero): text` · `… to you: text` · `… to Other (Hero): text` · `Name (Hero) wants to stop the robot!` |
| System | ⓘ (yellow) | `[Name] started playing Overwatch.` · `You have joined a group!` · `You endorsed Name!` |
| Group chat | not seen yet | — |

- Brackets wrap the **name**, not the channel; channel = icon + colour.
  `[Match] …` only appears as the input prompt of an open chat box — ignore it.
- Colours are user settings → sample at calibration, never hardcode.
- Long messages wrap onto an indented line without icon → join them.
- Default chat region at 2560×1440: x 55–670, y 510–905 (see #10).
- There is **no** chat duration/opacity setting; chat fades → 4 fps sampling.
- Strip trailing `[Report]` links and game icons; drop the half-cut top line of a scrolled chat.
- Best end-of-match signal: subtitle box `[ATHENA] Victory.` / `[ATHENA] Defeat.` (bottom centre), then the big banner (#21).

---

## Data model

```sql
schema_version (version)
sessions       (id, started_at, ended_at)
matches        (id, session_id, started_at, ended_at, outcome NULL,
                map NULL, mode NULL,
                source)   -- 'heroselect' | 'endscreen' | 'gap' | 'hotkey'
players        (id, display_name, verdict NULL, notes TEXT, first_seen, last_seen)
player_aliases (player_id, alias)
chat_messages  (id, match_id, ts, channel, speaker_raw, player_id NULL,
                hero NULL, text, ocr_confidence)   -- hero from comms-wheel lines
chat_fts       -- FTS5 over chat_messages(text, speaker_raw)
```

---

## GUI

**The design is decided: [`docs/ui.md`](docs/ui.md) + the mockups in
`docs/ui/mockup/`.** Read both before any UI work and match them — colours,
fonts, stickers, wording. The app must look good from the very first window
(#3); a plain default NiceGUI look is not acceptable, even temporarily.

In short: simple layout, Overwatch energy, slightly silly.
- **Silly lives in words, colours and motion. The layout stays boring.**
- Dark "night" ground, **payload orange** accent, chunky arcade buttons, cards
- Barlow Condensed 800 italic uppercase for headings/names, Nunito Sans for text
  (bundled with the app, no network at runtime)
- Verdicts are tilted stickers: Bestie · Fun · Meh · Nope
- UI vocabulary: yaps, yappers, "Look who's back!", "Who's that?"
- No emoji, no Blizzard fonts/logos/art
- Every UI PR includes a screenshot

Default hotkeys (configurable): `Ctrl+Alt+F` bring YapTracker forward + focus
lookup · `Ctrl+Alt+M` new match (override only) · `Ctrl+Alt+P` pause
(auto-resumes next match). **Nothing in normal play may depend on a hotkey.**

---

## Test data

- `human` task for Marv/Void: 20–30 screenshots (and optionally one short clip)
  with chat visible — team, match, group and system lines, at their real
  resolution. Stored in `fixtures/private/`, never committed.
- Marv also has **full OBS match recordings** (kept on Windows, e.g. under
  `/mnt/c/Users/.../Videos/`). Don't ask him to cut them: `tools/extract_frames.py`
  (see its issue) turns them into 4 fps chat-region frames + 1 fps full frames in
  `fixtures/private/frames/` — the main input for replay tests, dedup and match
  detection. Extract when he isn't playing.
- From those, generate committed fixtures: OCR-output JSON with names swapped
  for fake ones, plus expected parse results.
- Unit tests: parser, dedup, matcher. Replay tests: frame sequence → expected
  message list.
- From M2 on, the app **collects its own samples** (#63): hard chat frames and
  match-signal frames land in `%LOCALAPPDATA%\YapTracker\data\debug\`, readable from
  WSL at `/mnt/c/Users/marvi/AppData/Local/YapTracker/data/debug/`. Use them for new
  tests instead of asking Marv for screenshots. Same privacy rules as `fixtures/private/`.

---

## Definition of done (v1.0)

- [ ] One real evening session (Marv + Void) produces a chat log they agree is
      correct enough to be useful
- [ ] They've written notes on at least three players, and the familiar-face
      card fired for someone they met before
- [ ] The whole evening needed **zero** YapTracker key presses or clicks
      (capture, matches, sessions all automatic)
- [ ] No noticeable FPS impact in Overwatch; YapTracker uses < 5% of one CPU core
- [ ] Update via `tools/update.ps1` works from any v0 pre-release to v1.0.0
- [ ] README: setup, calibration, hotkeys, known limits, tested resolution
- [ ] `v1.0.0` released, M5 closed, everything else is `parked`

When this list is done, **the project is done.** Say so, and stop.
