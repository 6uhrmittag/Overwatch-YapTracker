# Changelog

What changed in YapTracker, newest first, in plain words. Every merge is a pre-release on [GitHub](https://github.com/6uhrmittag/Overwatch-YapTracker/releases) with the same bullets as its release notes; `tools/update.ps1` installs the newest one and keeps your data.

## v0.5: on the way to v1.0

### 2026-10-03 · No more empty matches (#270)
- Sessions, search and exports skip matches with no lines and no result, including the ones left by pressing New match before a match.

### 2026-10-03 · Live says where the match is (#268)
- Live says whether you're in a match (map, mode, time), the match is over (Victory or Defeat), or you're between matches, where the next one starts by itself at hero select.
- After the result, the chat card says "Last match" and keeps its lines until the next match starts.

### 2026-10-03 · Lighter when busy (#249)
- After a minute above 15 % of a CPU core, YapTracker reads the chat every 3 s instead of every 1.5 s for the next minute. A line stays on screen ~9 s, so nothing is missed, and the game gets the CPU back.

### 2026-10-03 · Umlauts from the picture (#247)
- Umlauts are kept even when a line has no German word in it, like "nö", "jüt" or "täääätüüüü": YapTracker spots the dots in the line's picture.

### 2026-10-03 · Workflow (no issue)
- Behind the scenes: Claude Code pushes and merges its own PRs once CI is green (CLAUDE.md).

### 2026-10-03 · A black game window: the screen instead (#236)
- If Windows only sends a black picture of the Overwatch window, YapTracker reads the screen Overwatch is on instead and says so in Live. It tries the window again at the next start.

### 2026-10-03 · update.ps1 fits the window and keeps itself current (#246)
- The download bar stays on one line, also in a narrow window or Windows Terminal: it gets shorter instead of wrapping.
- Your saved `update.ps1` updates itself first, so you always get the newest one, including the "what's new" after an update.

### 2026-10-03 · Hotkeys on any keyboard (#245)
- Hotkeys work with any keyboard layout (Dvorak, QWERTZ…): the letter you press is the one saved, shown and used.
- Ä, Ö, Ü and ß are refused with a hint: Windows can't use them as hotkeys.

### 2026-10-03 · Lighter on Windows 10 (#248)
- Windows 10: YapTracker now copies only the chat box from the screen instead of every frame the game draws. That was costing Void a lot of FPS.
- No more yellow border around Overwatch on Windows 10.

### 2026-10-03 · Capture modes measured (#229)
- Behind the scenes: measured how each way of capturing affects the game's FPS in a real match. None caps Overwatch at the refresh rate, so capture stays as it is.

### 2026-10-03 · Release notes in plain words (#239)
- Every release now says what's new in plain words, and this changelog keeps the list.
- After an update, `tools/update.ps1` tells you what's new.

### v0.5 so far (2026-10-02 and 03)
- A README with a quick start, install, calibration, hotkeys and the known limits.
- Windows 10 records again: the capture asked for settings only Windows 11 has.
- "Use GPU for OCR" is gone: it made Overwatch stutter. Reading stays on the CPU, and the window can't freeze any more while the reader loads.
- A verdict in one click: in the Yappers list, or by clicking a name in the chat.
- Fix or delete a chat line right where you see it, with Undo. Fixed lines keep a small "edited" mark, and Edit toggles, one line at a time.
- Chat text can be selected and copied in the app window, one "Name: message" per line.
- Half a screen is enough: every view works from 720 px wide, next to OverLooker.
- Group and system lines are recognised by their icons, with Void's colours too.
- Overwatch in Fullscreen and Windows sends only black? YapTracker says so, and how to fix it.
- `tools/update.ps1` pushes a payload progress bar and downloads faster.
- Behind the scenes: the game's FPS (from Overwatch's own counter) and the PC's system info go into the log, so YapTracker's cost can be measured.

## v0.4: Browse (M4)
- Sessions: every evening, match by match, with the full transcript and the times nothing was recorded.
- Search across all chat: half words, a name, or both, with channel and time filters.
- Exports: your yappers, or everything as documented JSON and Markdown, names anonymised if you like.
- Yap snaps: pick some lines, get a pretty PNG in one of several styles, names hidden by default.
- Settings for reading, hotkeys, start with Windows, your data folder and daily backups.
- Better reading on 4K and HDR screens; comms-wheel callouts dimmed and counted; group chat gets its own colour.

## v0.3: Remember people (M3)
- Yappers: everyone you've met, with verdict stickers (Bestie, Fun, Meh, Nope), notes that save themselves and every yap they wrote.
- "Look who's back!": a card pops up when someone you've met before types in chat.
- "Who's that?": look up a name from the scoreboard (Ctrl+Alt+F), typos forgiven.
- Merge two yappers that are one person, or add someone by hand.
- Spicy yaps: lines Overwatch or you marked, with a heads-up when those players are back. Never an automatic verdict.

## v0.2: Live chat log (M2)
- Live: the chat streams in while you play and is kept on your PC.
- Zero-touch: starts with Windows, records when Overwatch runs, finds matches and sessions by itself.
- You and your crew are known: your lines say "you", and the crew never gets a "Look who's back!".
- When recording stops, an orange banner says so, it restarts by itself, and the lost time is kept as a gap.
- First-start setup: find Overwatch, draw the chat box, tell it who you are.
- Pause (Ctrl+Alt+P) resumes by itself at the next match.

## v0.1: Read a screenshot (M1)
- Draw the chat box on a screenshot.
- YapTracker reads the lines in it: who said what, and in which channel.
- RapidOCR reads best, Windows OCR is the backup.

## v0.0: Skeleton (M0)
- The app window, in its night look with the nav rail.
- Every change builds on GitHub and becomes a pre-release; `tools/update.ps1` installs and updates it without touching your data.
