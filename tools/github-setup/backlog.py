"""YapTracker GitHub backlog: labels, milestones, issues.

This is the record of how the repo's issues were created. `apply.py` reads it.
Placeholders like {{#screenshots}} are replaced with the real issue number.
"""

LABELS = [
    # name, colour, description
    ("blocker", "b60205", "Timebox hit; fallback in use. Explains what was tried"),
    ("bug", "d73a4a", "Something that worked is broken"),
    ("human", "7057ff", "Only Marv/Void can do this - Claude Code: don't start it"),
    ("needs-decision", "fbca04", "Waiting on Marv; all open questions in one comment"),
    ("parked", "bfbfbf", "Good idea, not v1. Never build without Marv's explicit OK"),
    ("priority", "ff9c2a", "Do this first once unblocked - Marv asked for it explicitly"),
    ("quick-win", "0e8a16", "Fits in one match (~10 min, reviewable in a queue)"),
    ("spike", "c5def5", "Research with a hard 45 min timebox; result goes to docs/decisions.md"),
    ("ci", "1d76db", "Build, release and update pipeline"),
    ("ux", "d876e3", "Look & feel polish"),
    ("docs", "0075ca", "README and documentation"),
    ("area:capture", "f9d0c4", "Getting frames from the screen"),
    ("area:ocr", "f9d0c4", "Turning pixels into text"),
    ("area:parser", "f9d0c4", "Channel/speaker/text parsing and dedup"),
    ("area:storage", "f9d0c4", "SQLite, sessions, search"),
    ("area:players", "f9d0c4", "Player memory: notes, verdicts, matching"),
    ("area:ui", "f9d0c4", "Windows, views, hotkeys"),
]

# GitHub's default labels we don't use (kept: bug, duplicate, wontfix)
DELETE_LABELS = ["documentation", "enhancement", "good first issue", "help wanted", "invalid", "question"]

MILESTONES = [
    ("M0 - Skeleton & pipeline",
     "An empty dark YapTracker window you can install from a GitHub pre-release and update with one command. "
     "No OCR yet - this milestone exists so every later change reaches Marv's PC in minutes."),
    ("M1 - Read a screenshot",
     "Point YapTracker at a screenshot and it shows the chat lines it read: channel, speaker, text. "
     "The OCR engine is picked with evidence."),
    ("M2 - Live chat log",
     "Play a match and watch the chat appear in YapTracker, each line once, saved locally. "
     "First moment of real value."),
    ("M3 - Remember people",
     "Write notes and verdicts on players, and get a familiar-face card when someone you know types in chat. "
     "The heart of the app."),
    ("M4 - Browse",
     "Look back at past sessions and matches, search all chat, export your player notes."),
    ("M5 - v1.0",
     "One real evening with Void proves it works. README done, v1.0.0 released. Then the project is DONE."),
]


def body(goal, see, done, notes=None, blocked=None):
    parts = [f"**Goal**\n{goal}", f"**You'll see**\n{see}",
             "**Done when**\n" + "\n".join(f"- [ ] {d}" for d in done)]
    if notes:
        parts.append(f"**Notes**\n{notes}")
    if blocked:
        parts.append("**Blocked by** " + ", ".join(f"{{{{#{b}}}}}" for b in blocked))
    return "\n\n".join(parts)


# key, milestone index (None = no milestone), labels, title, body
ISSUES = [
    # ---------------------------------------------------------------- M0
    ("scaffold", 0, ["quick-win", "ci"], "Scaffold the Python project", body(
        "A clean Python 3.12 project that installs, lints and tests with one command each.",
        "`pip install -e .[dev]`, `ruff check` and `pytest` all pass locally and in a fresh clone.",
        ["`pyproject.toml` with package `yaptracker` under `src/`",
         "ruff + pytest configured, one trivial passing test",
         "`python -m yaptracker --version` prints the version",
         "Short dev setup section in README"])),
    ("ci-tests", 0, ["quick-win", "ci"], "CI: lint and tests on every PR", body(
        "Every PR is checked automatically so Marv only reviews the outcome, not the basics.",
        "A green check on PRs.",
        ["GitHub Actions workflow runs ruff + pytest on `ubuntu-latest` for PRs and pushes to `main`",
         "Workflow fails on lint or test errors"],
        blocked=["scaffold"])),
    ("window", 0, ["area:ui"], "App opens a dark window with the nav rail", body(
        "The YapTracker look exists from day one, so every later feature lands in a real app.",
        "A dark YapTracker window with a left icon rail (Live, Yappers, Sessions, Search, Settings) and empty placeholder views.",
        ["NiceGUI in native mode opens a window titled YapTracker",
         "Looks like docs/ui/mockup/Live.dc.html: colours, fonts (bundled), orange logo, icon rail - no default NiceGUI look",
         "Switching between the five views works",
         "Settings → About shows the app version"],
        notes="Packaging trouble? Fallback order is in CLAUDE.md: Edge app window, then plain browser tab.",
        blocked=["scaffold"])),
    ("win-build", 0, ["ci"], "CI: Windows build artifact on every PR", body(
        "Marv can download and run any PR during a queue without building anything locally.",
        "Each PR has a downloadable `YapTracker-<version>-win64.zip` under Checks → Artifacts.",
        ["Workflow on `windows-latest` builds a PyInstaller one-folder app",
         "Zip uploaded as artifact",
         "The zipped app starts on a clean Windows user account"],
        notes="45 min timebox. If NiceGUI native mode won't package, switch to the documented fallback and file a `blocker` issue.",
        blocked=["window"])),
    ("prerelease", 0, ["ci"], "CI: pre-release on every merge to main", body(
        "Every merged PR becomes an installable release automatically.",
        "A new GitHub pre-release `v0.<milestone>.<run_number>` with the zip attached after each merge.",
        ["Workflow on push to `main` builds and publishes a pre-release",
         "Release notes list merged PR titles since the last release",
         "Version inside the app matches the release tag"],
        blocked=["win-build"])),
    ("update-script", 0, ["ci", "quick-win"], "tools/update.ps1: one-command update", body(
        "Updating YapTracker takes one command during a queue and never touches Marv's data.",
        "Run `tools/update.ps1` → latest pre-release is downloaded and installed, app restarts.",
        ["Downloads the newest (pre-)release zip from GitHub",
         "Replaces `%LOCALAPPDATA%\\YapTracker\\app`, never touches `...\\data`",
         "Closes a running YapTracker first, starts it afterwards",
         "Works in Windows PowerShell 5.1 and PowerShell 7"],
        blocked=["prerelease"])),
    ("screenshots", 0, ["human"], "Collect 20-30 screenshots with chat visible", body(
        "Real test material for OCR - the only input Claude Code can't produce itself.",
        "A folder `fixtures/private/` on Marv's PC (gitignored, never committed) with the screenshots.",
        ["20-30 full-screen screenshots at the real resolution, chat box visible",
         "Mix of team chat, match chat, group chat and system lines (joins/leaves)",
         "At least a few with lots of lines, and a few mid-fade",
         "Optional: one 1-2 minute clip with chat activity",
         "Resolution + display mode written in a comment here"],
        notes="Win+Shift+S or the NVIDIA App screenshot hotkey both work. If your own text chat is still restricted, Void's screenshots are just as good.")),
    ("chat-settings", 0, ["human", "quick-win"], "Check Overwatch display & chat settings", body(
        "Know the settings capture depends on before building it.",
        "A comment on this issue with the answers.",
        ["Display mode set to **borderless windowed**",
         "Resolution noted",
         "Any chat options noted (display duration, size, opacity, profanity filter)",
         "Which monitor Overwatch runs on"])),

    # ---------------------------------------------------------------- M1
    ("framesource", 1, ["area:capture", "quick-win"], "FrameSource interface + replay from a folder", body(
        "Everything after capture can be built and tested without the game running.",
        "A developer command that feeds a folder of images through the pipeline stub.",
        ["`FrameSource` interface as described in CLAUDE.md",
         "`ReplayFrameSource` reads images from a folder at a configurable fps",
         "Unit tests run on Linux"])),
    ("calibrate", 1, ["area:ui"], "Chat-region calibration on a screenshot", body(
        "YapTracker knows exactly where the chat box is.",
        "Settings → Calibrate: pick a screenshot, drag a rectangle over the chat box, save.",
        ["Screenshot shown scaled to fit, rectangle can be dragged and adjusted",
         "Region saved per resolution in the config",
         "The cropped result is shown for confirmation"],
        blocked=["window"])),
    ("ocr-spike", 1, ["spike", "area:ocr"], "Spike: pick the OCR engine (45 min)", body(
        "Choose the OCR engine with evidence instead of guessing.",
        "A table in the PR and one line in `docs/decisions.md` with the decision.",
        ["RapidOCR and Windows OCR run on the cropped chat region of all private screenshots",
         "Per engine: rough character accuracy, name accuracy, ms per frame",
         "Decision recorded; loser kept as fallback behind a setting"],
        notes="Hard 45 min timebox. No clear winner → RapidOCR and move on.",
        blocked=["screenshots", "calibrate"])),
    ("ocr-view", 1, ["area:ocr"], "OCR a screenshot and show the lines", body(
        "See what YapTracker reads before anything is stored.",
        "A debug view: pick a screenshot → cropped chat box + list of recognised lines with confidence.",
        ["OCR runs on the calibrated region",
         "Lines grouped top-to-bottom with confidence",
         "Works with both engines"],
        blocked=["ocr-spike"])),
    ("parser", 1, ["area:parser"], "Line parser: channel, speaker, text", body(
        "Raw OCR lines become structured chat messages.",
        "In the debug view each line shows channel / speaker / text; system lines are marked as system.",
        ["Parses `[Team]`, `[Match]`, group and system lines (verify shapes on real samples)",
         "Anonymised fixtures (fake names) committed with expected results",
         "Unit tests pass",
         "Unparseable lines are kept with `channel = unknown`, never dropped"],
        blocked=["ocr-view"])),
    ("channel-colour", 1, ["area:parser", "quick-win"], "Detect channel from prefix colour", body(
        "Channel detection survives OCR mangling the `[Team]` brackets.",
        "Fewer `unknown` channels in the debug view.",
        ["Median colour of the prefix box maps to team/match/group/system",
         "Falls back to text-only parsing when unsure"],
        notes="Optional polish - drop to `parked` if it takes more than 45 min.",
        blocked=["parser"])),

    # ---------------------------------------------------------------- M2
    ("storage", 2, ["area:storage"], "SQLite store with migrations and auto-backup", body(
        "Chat and players are saved safely and survive updates.",
        "A `yaptracker.db` in the data folder; a backup appears before any schema change.",
        ["Schema v1 from CLAUDE.md, WAL mode, FTS5 table",
         "`schema_version` + migration runner",
         "DB copied to `data/backups/` before any migration",
         "Repository layer; UI never writes SQL"])),
    ("live-capture", 2, ["area:capture"], "Live capture of the Overwatch window", body(
        "YapTracker watches the chat box while you play.",
        "Live view status: 'Waiting for Overwatch' → 'Capturing' when the game starts.",
        ["WGC window capture of `Overwatch.exe`, cropped to the calibrated region, ~4 fps",
         "Detects game start/stop, no errors while the game is closed",
         "Tested on Marv's hybrid-GPU PC via a pre-release"],
        notes="45 min timebox per approach. Fallbacks in order: WGC monitor capture + crop, then `mss`.",
        blocked=["framesource", "calibrate"])),
    ("change-detect", 2, ["area:capture", "quick-win"], "Skip unchanged frames", body(
        "OCR only runs when the chat box actually changed - cheap on CPU.",
        "A 'frames skipped' counter in the Live view status.",
        ["Cheap diff/hash on the cropped region",
         "Configurable threshold, sensible default",
         "Unit test with replayed frames"],
        blocked=["live-capture"])),
    ("dedup", 2, ["area:parser"], "Store each chat line exactly once", body(
        "A line visible across 40 frames and scrolling upward is saved once.",
        "No duplicates in the log after a replayed chat sequence.",
        ["Fuzzy matching against recent lines with neighbour context (rapidfuzz)",
         "Keeps the highest-confidence reading",
         "Replay test: frame sequence in → expected message list out"],
        notes="Timebox 45 min, then fallback: exact match within 30 s.",
        blocked=["parser", "storage"])),
    ("live-view", 2, ["area:ui"], "Live view: chat streams in", body(
        "Watch the chat appear in YapTracker on the second monitor during a match.",
        "Messages appear within ~1 s, colour-coded by channel, newest at the bottom.",
        ["Live feed of stored messages for the current match",
         "Channel colours; system lines dimmed",
         "Auto-scroll that pauses when you scroll up"],
        blocked=["dedup", "live-capture"])),
    ("hotkey-pause", 2, ["area:ui", "quick-win"], "Hotkey: pause/resume capture", body(
        "Stop recording instantly, e.g. for private group chat.",
        "Ctrl+Alt+P toggles capture; status shows 'Paused' clearly.",
        ["Global hotkey via `RegisterHotKey` (never sends input to the game)",
         "Paused state visible in the Live view and window title"],
        blocked=["live-capture"])),
    ("matches", 2, ["area:storage"], "Split chat into sessions and matches", body(
        "Chat is grouped by evening and by match.",
        "The Live view shows 'Session 3 · Match 5'; Ctrl+Alt+M starts a new match manually.",
        ["New session after ≥ 30 min without capture",
         "New match on a time-gap heuristic or the Ctrl+Alt+M hotkey",
         "`source` column records which one"],
        blocked=["storage"])),
    ("perf-check", 2, ["human"], "Play test: CPU and FPS check", body(
        "Catch performance problems early, not at v1.0.",
        "A comment with numbers from one evening.",
        ["YapTracker CPU usage during a match (Task Manager)",
         "Any noticeable FPS drop in Overwatch? (yes/no)",
         "Did every chat line show up once?"],
        blocked=["live-view"])),

    # ---------------------------------------------------------------- M3
    ("matcher", 3, ["area:players"], "Link speakers to players", body(
        "Every chat message belongs to a player, even when OCR misreads a name slightly.",
        "Messages link to player profiles; OCR variants become aliases automatically.",
        ["Fuzzy match speaker against players + aliases",
         "Below threshold → new player",
         "Unit tests with noisy names"],
        blocked=["dedup"])),
    ("players-list", 3, ["area:players", "area:ui"], "Players view: list, search, filter", body(
        "Browse everyone you've met.",
        "Players view: sortable list with verdict colour, last met, number of matches, message count.",
        ["Filter by verdict, sort by last met / times met",
         "Search by name (fuzzy)"],
        blocked=["matcher"])),
    ("profile", 3, ["area:players", "area:ui"], "Player profile: verdict, notes, history", body(
        "Remember what you thought of someone.",
        "Click a player → verdict buttons (friend / fun / neutral / avoid), notes that save themselves, first/last met, all their messages, aliases.",
        ["Notes autosave (no save button)",
         "Verdict one click, shown in colour",
         "Message list grouped by match"],
        blocked=["players-list"])),
    ("familiar-face", 3, ["area:players", "area:ui", "ux"], "⭐ Familiar-face card in the Live view", body(
        "Greet people you've played with before. This is why YapTracker exists.",
        "When a known player types in chat, a big card appears: name, verdict colour, 'last met Sep 28 · 3 matches', first line of your notes.",
        ["Card appears within ~1 s of their message",
         "Impossible to miss on a second monitor",
         "Multiple known players stack; card fades after a while",
         "Click opens the profile"],
        blocked=["profile", "live-view"])),
    ("lookup", 3, ["area:players", "area:ui", "quick-win"], "Quick lookup hotkey", body(
        "Check someone who didn't chat - read the name off the scoreboard, type it.",
        "Ctrl+Alt+F brings YapTracker forward with a search box focused; results as you type; 'Add player' if unknown.",
        ["Global hotkey focuses the window and search box",
         "Fuzzy results in < 100 ms",
         "Add player from the search"],
        blocked=["players-list"])),
    ("merge", 3, ["area:players", "quick-win"], "Merge two players", body(
        "Fix it when OCR created two players for the same person.",
        "'Merge into…' on a profile combines messages, notes and aliases.",
        ["Notes concatenated, not lost", "Aliases combined", "Undo-safe: DB backup before merge"],
        blocked=["profile"])),

    # ---------------------------------------------------------------- M4
    ("sessions-view", 4, ["area:ui", "area:storage"], "Sessions view with transcripts", body(
        "Look back at last night's matches.",
        "Sessions → matches → full chat transcript; known players highlighted.",
        ["List of sessions with date, duration, match count",
         "Match transcript with channel colours",
         "Click a speaker → profile"],
        blocked=["matches", "profile"])),
    ("search", 4, ["area:ui", "area:storage"], "Search all chat", body(
        "Find 'who said that thing about Rein?'",
        "Search view: type → results with speaker, date, match, highlighted words.",
        ["SQLite FTS5 search", "Filters: channel, player, date range",
         "< 200 ms on 100k messages (test with generated data)"],
        blocked=["storage"])),
    ("export", 4, ["area:players", "quick-win"], "Export players and notes", body(
        "Player notes can leave the app - e.g. into the PersonalKnowledgeBase repo.",
        "Settings → Export → `players.md` and `players.json`.",
        ["Markdown: one section per player with verdict, last met, notes",
         "JSON: full player data incl. aliases"],
        blocked=["profile"])),
    ("settings", 4, ["area:ui"], "Settings view", body(
        "Everything configurable in one place.",
        "Settings: OCR engine, sample rate, hotkeys, data folder (open in Explorer), backup now, calibrate, about.",
        ["All settings persist", "Hotkeys can be changed and conflicts are shown"],
        blocked=["calibrate"])),

    # ---------------------------------------------------------------- M5
    ("readme", 5, ["docs"], "README for v1", body(
        "Someone else (or future Marv) can set it up without help.",
        "README with setup, calibration, hotkeys, privacy, known limits, tested resolution.",
        ["Install + update instructions", "Calibration with one screenshot (no player names)",
         "Hotkey table", "Known limits"])),
    ("acceptance", 5, ["human"], "Acceptance evening with Void", body(
        "Prove v1 works in real life.",
        "One normal evening of Overwatch with YapTracker running.",
        ["Chat log correct enough to be useful",
         "Notes written on at least three players",
         "Familiar-face card fired for someone met before",
         "No noticeable FPS impact",
         "Findings listed as comments → bugs filed in {{#fixes}}"])),
    ("fixes", 5, ["bug"], "Fix what the acceptance evening found", body(
        "v1.0 ships without the annoying stuff.",
        "Everything from {{#acceptance}} fixed or consciously parked.",
        ["Only bugs and small polish - new features go to `parked`"],
        blocked=["acceptance"])),
    ("release-v1", 5, ["ci"], "Release v1.0.0 🎉", body(
        "The project is finished.",
        "A stable GitHub release `v1.0.0`; `tools/update.ps1` installs it.",
        ["Stable (non-pre) release v1.0.0",
         "Update from any v0 pre-release works",
         "All milestones closed, everything else `parked`",
         "Celebrate with Void"],
        blocked=["readme", "fixes"])),

    # ---------------------------------------------------------------- parked
    *[(f"parked-{i}", None, ["parked"], title, text) for i, (title, text) in enumerate([
        ("Import recordings / video files", "Run existing recordings (NVIDIA Instant Replay, OBS) through the OCR pipeline via ffmpeg."),
        ("Full lobby rosters via Overwolf game events", "Overwolf's Overwatch events include all 10 BattleTags. Needs Overwolf Electron and possibly app approval."),
        ("Read OverLooker's local files for match context", "Use OverLooker logs (read-only) to get match boundaries, map and roster."),
        ("Tab-scoreboard OCR for full rosters", "Detect the Tab scoreboard when Marv opens it and OCR all 10 names."),
        ("Tags for players", "Free-form tags like 'great Rein', 'German', 'funny'."),
        ("Review queue for low-confidence OCR", "Queue of uncertain lines with the source crop, edit/merge/discard."),
        ("PaddleOCR on the GPU", "Possibly better accuracy on stylised fonts using the RTX 4090."),
        ("Proper installer", "Inno Setup installer with start menu entry and uninstaller."),
        ("Autostart with Windows / with Overwatch", "Start YapTracker automatically."),
        ("In-app auto-updater", "Update button inside the app instead of tools/update.ps1."),
        ("Tray icon", "Minimise to tray, quick pause from the tray menu."),
        ("Statistics & charts", "Who we meet most, chat activity over time, etc."),
        ("Share player notes between Marv's and Void's PCs", "Both of us see the same player memory. Needs sync (file share, Syncthing or a tiny server)."),
    ])],
]

ROADMAP_TITLE = "🗺️ Roadmap - start here"
