# Changelog

What changed in YapTracker, newest first, in plain words. Every merge is a pre-release on [GitHub](https://github.com/6uhrmittag/Overwatch-YapTracker/releases) with the same bullets as its release notes; `tools/update.ps1` installs the newest one and keeps your data.

## v0.5: on the way to v1.0

### 2026-10-06 · Gentler on Windows 10 (#319)
- On Windows 10, YapTracker copies from the screen far less often: the chat box twice a second instead of 4 times (once while nobody types), and the match screens in 4 pieces instead of 7. The game waits for each copy, so it waits much less.

### 2026-10-04 · No more fake matches (#307)
- Chat outside a match (login lines, the Practice Range while you queue) no longer counts as a match of its own. It shows at the top of the next match, before a "The match starts" line, with a minus time.

### 2026-10-04 · A quality floor in CI (#310)
- Behind the scenes: the checks now fail if test coverage drops under 80 % or a function gets too tangled, and a slow test machine can't turn them red any more.

### 2026-10-04 · Locked versions (#309)
- Behind the scenes: every build uses exactly the library versions of v0.5.327, so an update only changes what YapTracker's own code changes.

### 2026-10-04 · Friend-list notices aren't familiar faces (#306)
- "[Name] stopped playing Overwatch." and "[Name] started spectating." are system lines now: no more "Look who's back!" card for a friend going offline. System lines never count as meeting someone, and the ones already stored are fixed at the next start.

### 2026-10-04 · Hero select on bright maps (#300)
- Matches on very bright maps start at hero select again, even when HDR washes out the "ASSEMBLE YOUR TEAM" banner: YapTracker also knows the "F1 HERO DETAILS" hint at the bottom of the screen, so these matches show their mode in Sessions like the others.

### 2026-10-04 · Lighter match detection (#303)
- YapTracker looks for the hero-select screen every few seconds instead of every second (every 5 s in a match, 2 s between matches). It still catches every match start and uses about 2 % less of a CPU core.

### 2026-10-04 · Where the CPU goes (#302)
- Behind the scenes: once a minute the log says how much CPU each part takes (reading, change detection, match signals, debug samples, capture, the rest), and the game-FPS line says whether you're in a match or between matches.

### 2026-10-04 · The window fits its screen again (#299)
- YapTracker no longer comes back taller than its screen: it never opens bigger than the screen it's on, the title bar stays reachable, and on a screen with different scaling it gets moved a second time to land where you left it.

### 2026-10-04 · Repeats keep their neighbours (#296)
- When someone says the same thing again a few seconds later, the repeat and the lines in between are all kept. Before, they could go missing.

### 2026-10-04 · Better readings replace, not repeat (#293)
- When YapTracker reads a line again and finds its umlauts ("müp möp" after "mup mop"), the better reading replaces the first one instead of showing up as a second line.

### 2026-10-04 · Steadier CI (#273)
- Behind the scenes: the Windows capture test accepts the runner refusing capture settings, which the app already handles, so CI stops failing at random.

### 2026-10-04 · Long umlaut runs (#266)
- Stretched words keep every umlaut too: "täääätüüüütatäääää" now reads exactly as typed.

### 2026-10-04 · Callouts read right (#290)
- Callouts are written as the comms wheel says them: "Eall back!" becomes Fall back!, "Enemy llari!" Enemy Illari!, and pieces like "My" or "/ Enemy" are no longer lines of their own.
- A callout read once with a garbled name is the same line as the clear one, not a second yap.

### 2026-10-04 · Callouts out of the way (#289)
- Live and match transcripts hide comms-wheel callouts ("Group up!", "Enemy Sombra!") by default, so the chat is what people typed. The Callouts switch next to the channel names shows them again, with a count of how many are hidden.

### 2026-10-04 · Real map, mode and hero names (#276)
- Maps, modes and heroes are matched against Overwatch's real names: "ESPERANCA" becomes Esperança, "Zenyata" Zenyatta, and garbage like "INRONKED ALU9CK" is left out instead of stored.

### 2026-10-04 · Fix a line's channel (#283)
- Click a chat line and pick Team, Match, Group or System when YapTracker got the channel wrong. Undo is right there, and a later reading never changes it back.

### 2026-10-04 · Heart a match (#282)
- Heart a match with one click in Live, while it runs or right after, to find it again: Sessions shows the heart, and you can heart a match there afterwards too.

### 2026-10-04 · What's new since your version (#281)
- After an update, `tools/update.ps1` lists everything that's new since the version you had, not just the newest release. Umlauts and icons print cleanly in every PowerShell.

### 2026-10-03 · Matches split right (#275)
- Hero select is seen on very bright maps too (New Junk City after the map vote), so the match starts there, not with the next chat line.
- Restarting YapTracker mid-match (an update) no longer splits the match in two: it goes on.

### 2026-10-03 · Icons stay put (#259)
- A line's picture now shows the whole row: the channel icon, the full name, the text and the icon at the end, so ◇ always points at something you can see.
- "Thanks!", "Group up!", "Fall back!" and "I need healing!" always get their ◇, and a ◇ seen once doesn't vanish on a later reading.

### 2026-10-03 · Unsent typing stays private (#254)
- What you type in Overwatch's chat box isn't saved until you send it. No more garbled messages from someone called "Mateh".

### 2026-10-03 · Opens where you left it (#253)
- YapTracker opens on the same screen, at the same place and size (maximised too), also after an update. No more dragging it to the second screen every evening.
- If that screen is unplugged, it opens at the usual place. Settings → About → Reset window position brings it back if it's ever out of reach.

### 2026-10-03 · No more empty matches (#270)
- Sessions, search and exports skip matches with no lines and no result, including the ones left by pressing New match before a match.

### 2026-10-03 · Start match / End match (#269)
- The New match button now says what it does: End match during a match, Start match between matches. It's rarely needed, because matches start at hero select and end at the result screen.
- Pressing it twice, or just before a long queue, no longer leaves empty matches. A press right before hero select becomes that match.

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
