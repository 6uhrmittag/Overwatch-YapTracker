# Changelog

What changed in YapTracker, newest first, in plain words. Every merge is a pre-release on [GitHub](https://github.com/6uhrmittag/Overwatch-YapTracker/releases) with the same bullets as its release notes; `tools/update.ps1` installs the newest one and keeps your data.

## v0.5: on the way to v1.0

### 2026-10-16 · Spicy marks stay put (#460)
- A line you marked spicy keeps its mark when YapTracker reads it again or tidies up after the match, so the heads-up when that player is back really comes. Overwatch's own report mark stays too.

### 2026-10-16 · The evening's CPU number is the real average (#476)
- Settings → About: an evening's "whole app … of a core" is now the average over the whole evening, not only of the minutes while chat was being read, so it's lower and fairer (one of Void's evenings: 18 % instead of 37 %). Evenings already listed keep their old number.
- README → Known limits: what to do on Windows 10 or an older CPU, and what YapTracker costs between matches.

### 2026-10-16 · A broken settings file no longer stops YapTracker (#456)
- If the settings file got broken (a power cut or a full disk while it was saved), YapTracker starts with the default settings, keeps the old file in the data folder and says so once in Live.
- Settings are now fully on disk before they replace the old file, so a power cut leaves the old or the new settings, never a broken file.

### 2026-10-16 · Lighter on your PC in matches (#115)
- In a match YapTracker now looks at the game 2 times a second instead of 4, like between matches. A chat line stays on screen for about 9 seconds, so it is still seen many times; the copying of the game picture costs about half as much.

### 2026-10-16 · Stable releases are promoted test versions (#454, part 2)
- Behind the scenes: a stable release is a tested build published again as it is (workflow "Promote pre-release to stable", only when Marv says so); its notes gather everything since the last stable release. After v1.0.0, test versions are named like v1.1.0-pre.512. README explains stable vs test versions.

### 2026-10-16 · Stable releases, test versions if you want them (#454)
- Settings → About has a new switch, "Get test versions (pre-releases)": off means you get stable releases only. Until the first stable release (v1.0.0) is out, every new build still reaches you.
- `update.ps1` installs the newest stable release; `update.ps1 -PreRelease` installs the newest test version.

### 2026-10-16 · FPS check compares the same map (#448)
- Behind the scenes: `tools/evidence.py` compares YapTracker running vs paused on the same map only, and leaves out hero-select and partial minutes, so the FPS verdict no longer blames YapTracker for a heavier map.

### 2026-10-16 · A full disk or a hiccup in Windows OCR no longer loses chat (#452)
- When a line's picture or a debug sample can't be saved (for example on a full disk), the chat line is still saved. Read again then says the line has no picture.
- With less than 1 GB free, debug samples pause and Live says so: "Disk almost full: debug samples paused". They start again by themselves once there's space.
- When Windows OCR gives up on a frame ("Operation aborted"), it tries once more, and then the best reader reads that frame. No frame is lost.

### 2026-10-16 · Settings kept in memory (#451)
- The app window keeps its place again, also when it moves at the same moment as a match signal.
- No more short "crash" gaps in recording when settings are saved: the capture never reads the settings file anymore, and a save that finds the file busy simply tries again.

### 2026-10-13 · Live card header on one line (#449)
- In Live, "Make a yap snap", the channel colours and the Callouts switch now sit on one line.

### 2026-10-12 · The export's Markdown by day (#443)
- With Markdown on, the export has one file per day you played (`days/2026-10-11.md`), like the Sessions tab: a late night stays in the day it began, matches are numbered in their day, and breaks show between play blocks. The JSON keeps its sessions and also tells each match's day and number in it.
- Map names keep their own spelling ("Throne of Anubis", not "Throne Of Anubis"), in Sessions and in the export.

### 2026-10-12 · The FPS line says how chat was read (#444)
- Behind the scenes: each in-match minute of the game's FPS in the log now names the reader that read chat in it (best or light); when chat was quiet, the reading set for that match (after: read after the match). So the FPS check per reading mode compares like with like.

### 2026-10-12 · Sessions by day (#440)
- Sessions lists the days you played: one row per day with the time you really played, how many matches and yaps. A late night counts to the day it began, until 5 in the morning.
- A day shows all its matches numbered 1, 2, 3... with a quiet "Break, 1 h 20 min" between play blocks.
- Search results, profiles and Live number matches per day too, and a search result opens its match inside its day.

### 2026-10-12 · Evidence script (#437)
- Behind the scenes: `tools/evidence.py <data folder>` answers the waiting issues from the logs, a copy of the database and the debug samples (CPU per evening, FPS running vs paused per reading mode, Competitive matches and rounds, ranked end samples, notes and familiar faces), as plain text with ids only.

### 2026-10-12 · Every PR gets a code review
- Behind the scenes: every change now gets an automatic code review before it is merged; clear findings are fixed in the same change, bigger ones become bug issues.

### 2026-10-12 · The evening line counts more (#437)
- Behind the scenes: the evening line in the log also counts Competitive matches (with their merged rounds), familiar faces shown (live and after the match) and players with notes, and each familiar-face card is one log line (player ids only), so the Definition-of-done checks come from the log.

### 2026-10-12 · Light reading checked against a real match (#432)
- Behind the scenes: a replay of a real Quick Play match read live and light (54 chat frames, names made up) proves that after the tidy-up it has exactly the lines the best reader stores on its own: no repeats, no pieces, nothing missing.

### 2026-10-11 · Map names written right (#435)
- Sessions writes map names like "King's Row" instead of "King'S Row".
- Matches from the first days get their map and mode from the game lists once ("3 Colo Seo" becomes Colosseo); what was only misread text is cleared. A backup is made first.

### 2026-10-11 · The tidy-up shows itself and clears up (#432)
- The tidy-up after a light match says in the log when it starts, pauses for the next match, resumes and finishes ("tidied match N: … fixed, … found, … removed").
- It removes light-read repeats and pieces that the best reader doesn't see in the same moments; lines you fixed or flagged by hand always stay.

### 2026-10-11 · Light reading: no repeats, no fragments (#432)
- Opening the chat box no longer stores its history again as new lines, also when the light reader can't read the input row.
- A line the light reader read only in part ("so please n", "were in the") is no line of its own anymore: it belongs to the whole line, and a whole reading that comes later replaces the part.
- A line found between two known lines is stored only once it was read the same way twice.

### 2026-10-11 · Other matches read live and light by default (#413)
- New installs read "Other matches" live and light: it costs your game almost nothing, and the best reader tidies up afterwards. Competitive stays "After the match". A choice you already made stays as it is.

### 2026-10-11 · What's new after an update (#412)
- After an update, YapTracker shows once what changed since the version you had: "Fresh paint! Here's what changed since …". Never in a match: it waits until the match is over.
- Settings → About → "What changed in v…" shows it again any time.

### 2026-10-11 · Missed lines become a number (#425)
- When YapTracker reads a chat line twice but doesn't store it, the log says so ("seen twice but never stored") and keeps a debug sample of that moment. The evening line counts them, so missing lines show up as a number instead of a feeling.

### 2026-10-11 · No empty lines, no new player for a misread callout name (#424)
- A callout whose message wasn't read yet is no longer stored as an empty line; the full line comes with the next read. The empty lines already stored go once at the next start (a backup is made first).
- A callout with a misread name (one letter off) keeps the name its hero had in the lines before, so it stays with the right player, and your crew stays your crew.
- Behind the scenes: real player names that slipped into the code and the changelog with #423 are replaced by made-up ones.

### 2026-10-11 · The chat field's hint is no line (#422)
- "PRESS TAB TO CYCLE CHANNELS", the hint in Overwatch's empty chat field, is never stored as a line from "Match" anymore. The one already stored goes at the next start, with the player "Match" it made (a backup is made first).

### 2026-10-11 · Missed lines are stored after all (#423)
- A line that one read missed and a later read found between two stored lines is stored now, in its place, in the match it belongs to. Two lines after a match on Oct 11 were lost this way.

### 2026-10-11 · Second screen: it stays where it opens (#420)
- On your second screen YapTracker stays where it opens, at the saved place, instead of jumping up with its title bar above the screen. A move after the start was what pushed it up; there's none anymore when the screen has other scaling than the main one.

### 2026-10-11 · Friend notices start no match (#417)
- A friend notice in the menu, like "2 friends playing Overwatch.", no longer starts a match that then runs until the next hero select. Only typed chat and callouts do. The notices are still kept, as lines outside a match.

### 2026-10-11 · Update now, whenever you like (#416)
- Update now always says Update now and works when you click it, also while YapTracker thinks a match runs. It used to say "After this match" and stay greyed out, even in the menu.

### 2026-10-11 · Title bar fully on the screen (#414)
- YapTracker's title bar is no longer cut off at the top of your second screen: a window is never placed above its screen's top edge, only Windows' invisible border at the sides and below may stick out. A place saved 10 px too high moves down at the next start.

### 2026-10-11 · Opens at its size on a second screen (#410)
- YapTracker opens on your second screen at the size you left it, instead of too tall with its top above the screen. It's born right there, and Windows no longer gets the place in two different units when the second screen has other scaling than the main one.

### 2026-10-11 · Fewer false ◇ (#402)
- Plain lines no longer get a ◇ for an icon that isn't there. It came from the game's scenery right after a short line: something bright behind it for a moment. A ◇ now needs the icon in at least half of the readings, and bright scenery doesn't count.
- System lines (`[Name] left the game.`, `You endorsed …!`) never get one, and a `[Report]` link with a ◇ after it is still taken off and marks the line spicy.
- Lines you already have are checked once against their picture, in the background between matches: where no icon is there, the ◇ goes. The pictures stay as they are.

### 2026-10-11 · Clicking the tab you're on (#404)
- Clicking the icon of the tab you're already on no longer reloads it with the opening animation: on its main view nothing happens, so your scroll position and what you typed stay. Live never reloads or clears.
- From a player's profile, a match transcript or calibration, that same icon takes you back to the tab's list or overview, without the animation.

### 2026-10-11 · Your chat colours (#401)
- Chat lines take Overwatch's own colours: Team `#00c1ff`, Match `#fd8d00`. System lines stay grey, and lines without a channel ("Chat") too.
- Settings → Chat colours: pick each channel's colour (picker or hex) and see a line in it right away, no restart. Reset to Overwatch defaults puts them back. A colour that's hard to read on the dark background says so, but you can keep it.
- Yap snaps in the YapTracker night look use your chat colours, and system lines in a snap take the system colour like in Live.

### 2026-10-11 · Fewer lines filed as Chat (#403)
- Match and team lines on a bright map (snow, sky, white walls) now get their channel from the diamond or the team icon in front, instead of landing in grey Chat.
- Comms-wheel lines like `Name (Hero): Hello!` and system lines like `[Name] left the game.` are read again when the icon in front came out as a stray mark or space.
- When the icon can't be seen, YapTracker no longer guesses Team or Match from the colour on an HDR screen, where both look the same yellow: such a line stays Chat instead of landing in the wrong channel. You can still move it with a click.
- Settings → About → Last evenings has a Chat column: the share of lines YapTracker couldn't place in Team, Match or Group, to watch it. Earlier evenings get it filled in from what's stored.

### 2026-10-11 · One switch per row (#397)
- Export and yap snaps: every switch has its own row and says right under it what it does, instead of several switches side by side with one hint for all.
- Line pictures switch off while Anonymize names is on (they show the names), and Keep me & my crew only works with Hide names. Both are greyed out until then and say why.

### 2026-10-11 · Pre-releases again (#398)
- Behind the scenes: two hiccups in the build had stopped new pre-releases after v0.5.420. This one also brings the lighter capture between matches (#350).

### 2026-10-10 · Lighter between matches (#350)
- Between matches YapTracker now asks Windows for 2 pictures of the game a second instead of 4, in a match still 4. Windows copies the whole game window for each one, and between matches that was the biggest part of YapTracker's CPU. Menu chat stays on screen for seconds, so nothing is missed.

### 2026-10-10 · Choose how much space line pictures take (#389)
- Settings → Your data has a slider for the line pictures, from 50 MB to 5 GB (2 GB unless you change it). It shows what's used against the limit: "Line pictures: 78 MB of 2 GB".
- Lowering it says first what goes ("Frees 340 MB: the pictures before August go") and deletes it when you let go, oldest months first. Raising it deletes nothing.

### 2026-10-10 · Settings opens at once (#387)
- Settings opens right away again instead of after 1–2 seconds. The sizes of the line pictures and debug samples are counted once when YapTracker starts, and show "…" for that moment.
- Behind the scenes: saving a debug sample no longer re-measures every older sample, and any view that takes 150 ms or more to open says so in the log (`ui: settings took … ms`).

### 2026-10-10 · CPU by thread (#350)
- Behind the scenes: once a minute the log now also splits YapTracker's CPU by thread (`cpu threads: …`), to find where the time between matches goes. Most of it doesn't belong to any measured part yet.

### 2026-10-10 · Update now (#46)
- **Update now** in the update banner, in What's new and in Settings → About: YapTracker closes, a window shows the download, and the new version starts by itself. Your data stays where it is.
- During a match the button says **After this match**: an update never interrupts a game.
- If the update fails (no internet, say), the window says why and YapTracker starts again as it was.

### 2026-10-10 · A new version? YapTracker tells you (#46)
- When a newer YapTracker is out, Live shows a calm banner with **What's new** (every change since your version) and **Later**. Settings → About says the same, with **Check now**.
- YapTracker asks GitHub once a day which version is newest, never during a match. Nothing else is sent. Settings → About → **Check for updates once a day** switches it off.

### 2026-10-10 · The map from the end screen (#383)
- A match whose hero select YapTracker missed now gets its map from the end screen ("VICTORY ESPERANÇA"), so Sessions shows it too. A map that hero select already read is never replaced.
- Behind the scenes: if the end screen names another map than hero select did, the log says so. That's the check that YapTracker doesn't write wrong maps.

### 2026-10-10 · No more "typing" (#382)
- Overwatch doesn't show when someone is typing, and YapTracker never pretended to know: it sees lines once they're sent. The words now say so. Live says "Ears open. No new yaps right now.", and Sessions, Yappers, the export, Settings → About and the README say "writes in chat" or "no yaps" instead of "types".

### 2026-10-10 · More maps known (#378)
- Grímsvötn, the new Escort map, is now recognized. It was read correctly three times since yesterday, but YapTracker didn't know the name yet.
- When the queue and the map run together in one reading ("UNRANKED MIDTOWN"), or the map is washed out at first, hero select is now looked at again until the map is there too, not only until the queue is known.
- A match that the "HERO DETAILS" hint confirmed on a menu (role select, the map vote) now still gets its queue and map from the hero select that follows.

### 2026-10-10 · How well each evening was read (#379)
- Settings → About has a new **Last evenings** table: one row per evening with its matches, how often the map, queue and result were read, how many lines I wasn't sure about, how many you fixed by hand, and how much CPU YapTracker used. A real drop in reading quality now shows at a glance.
- The evenings since October 1 are filled in once at the first start, so there's something to compare with right away.
- Behind the scenes: at the end of every evening (Overwatch closed, YapTracker quits, or the next evening starts) the log gets one `evening` line with the same numbers and more detail.

### 2026-10-10 · A quiet chat no longer splits a match (#377)
- When nobody writes in chat for five minutes in the middle of a match, the next line now stays in that match instead of starting a new one without a map. A match ends with its end screen or the next hero select.
- Matches split like that before are put back together at the next start, with all their lines and the result. YapTracker backs up your data first, and the log names every merge.

### 2026-10-10 · Menu changes counted (#350)
- Behind the scenes: between matches, the log line "no chat in the box between matches" now also says how many frames looked new that minute, so the next evening shows how often the menu's art fools change detection.

### 2026-10-10 · Old split rounds put back together (#371)
- Competitive Escort and Hybrid matches that were split into two (one per side) are merged into one match at the next start, with all their lines, the heart and the result. YapTracker backs up your data first, and the log names every merge.

### 2026-10-10 · Competitive rounds stay one match (#364)
- In Competitive on Escort and Hybrid maps, where both teams take turns attacking, the side swap's hero select no longer starts a second match: Sessions shows one match with all its rounds.
- If YapTracker couldn't read the queue, a second round on the same map tells it the match is Competitive, so your Competitive reading choice applies from then on.

### 2026-10-10 · Yap snaps show names (#366)
- A yap snap now shows the names as they are. Switch on **Hide names** for a snap you post anywhere; it starts off each time.

### 2026-10-10 · Privacy test knows two more words (#369)
- Behind the scenes: the test that keeps real player names out of the code no longer mistakes two players named like ordinary words for a leak.

### 2026-10-10 · Opens on its own screen at its size (#365)
- YapTracker now opens straight on the screen you left it on, at the size you left it, instead of opening on the main screen and moving over. That should end the window coming back too tall on a second screen with other scaling.
- Behind the scenes: the log says how the window scales at every start (its DPI, its screen's DPI, its DPI awareness), and how it really landed after 1 and 3 seconds.

### 2026-10-07 · Quitting keeps the chat (#349)
- If you close YapTracker right after a ranked match, before it read that match's chat, the chat is kept and read at the next start, into the right match, with the times it was said.
- Behind the scenes: the crash note for unread chat was never written (a bug since #335); a crash mid-match now really shows up as "not recorded".

### 2026-10-07 · README: reading per kind of match (#361)
- The README explains in a few sentences how chat is read in Competitive and other matches, and what that can't do.

### 2026-10-07 · Read again says when it can't (#357)
- With line pictures switched off, or none left for a match, **Read again, best quality** is greyed out and says why, instead of running and finding nothing.

### 2026-10-07 · Back-to-back matches stay whole (#356)
- When the next match starts before the last one's chat was read, both wait together. If memory gets tight, YapTracker now drops only pictures that other pictures of the same match cover, never the first or last of a match, and the log says which match lost some.

### 2026-10-07 · An older version says so (#352)
- If an older YapTracker is started on data from a newer one, it now says so in its window ("Your data is from a newer YapTracker … run tools/update.ps1") instead of failing to start. It records nothing and leaves your data untouched.

### 2026-10-07 · CPU line per state (#351)
- Behind the scenes: the log's once-a-minute CPU line says whether that minute was in a match, between matches, paused or without the game, so each can be measured on its own.

### 2026-10-07 · Unknown queue: the lighter choice (#345)
- When YapTracker can't tell whether a match is Competitive (glare on hero select, or it started mid-match), it reads the chat the lighter of your two ways: After the match, then Live light, then Live best. So a ranked match never costs more than you chose for ranked.

### 2026-10-07 · Ranked spotted more often (#342)
- When hero select's queue ("COMPETITIVE", "UNRANKED"…) didn't read at first, YapTracker now looks again while hero select is up, also with two colour tricks against glare. So more ranked matches get their "Competitive" reading.

### 2026-10-07 · Lighter in the menus (#115)
- Between matches, when the chat box only shows menu art and no chat, YapTracker reads it every 6 s instead of every 1.5–3 s. As soon as a new line shows up, it's back to normal.

### 2026-10-07 · New season's hero (#318)
- The new hero Doctrine is known by name, so their callouts ("Enemy Doctrine!") count as callouts, not yaps.

### 2026-10-07 · Yap snaps from Live (#325)
- Live's chat card has **Make a yap snap**: click the lines you want (shift-click for a stretch), then Make the snap.
- Select two or more lines with the mouse and **Snap these** shows up right there.
- Sessions says where snaps are: "Open a match to read it back or make a yap snap."

### 2026-10-07 · Two lines no longer glued together (#329)
- When OCR read a name's brackets as I or l ("IBravolnCharliel: …"), the line was glued onto the one above. A row with its own chat icon now always starts a new line, and such a name comes out without the misread brackets.

### 2026-10-07 · No hotkeys unless you want them (#328)
- YapTracker no longer takes any key combo by default: everything has a button, and Ctrl+Alt is AltGr on German keyboards. Hotkeys you set yourself stay.
- Settings → Hotkeys shows "Not set" for each action, **Change** to set one and **Clear** to take it away again, right away.

### 2026-10-07 · Read again, best quality (#333)
- Sessions → a match → **Read again, best quality** reads every line again from its saved picture with the best reader and keeps a new reading only where it's better. A line's popup has **Read this line again**.
- It says how it's going ("Reading 23 lines again… 7 better so far.") and waits while a match runs. Lines you fixed by hand are never touched. It fixes misread lines; lines YapTracker never saw can't be found this way.

### 2026-10-07 · Light matches tidied up afterwards (#336)
- Competitive now reads **after the match** by default: your ranked FPS stays untouched.
- A match read "Live, light" gets tidied up once the game is idle: YapTracker reads its chat pictures again with the best reader, fixes misread lines and adds the ones Windows OCR missed, at the time they were said. Live says "Tidied up the last match: 3 lines fixed, 2 found."
- Lines you fixed or deleted by hand stay as they are. If the next match starts first, the tidy-up waits for the next break.

### 2026-10-07 · Read after the match (#335)
- Settings → Reading has a third choice for Competitive and for other matches: **After the match**. YapTracker keeps the chat pictures during the match and reads them once it's over, so your game pays nothing for the chat.
- Live says it in words during such a match: "Competitive: reading after the match. Your FPS stays untouched." Afterwards it counts down the pictures it still has to read.
- Faces from that match show up after it: "Look who was there!". Their lines keep the time they were said.
- If YapTracker closes before it could read them, the time shows up as "not recorded" in Sessions, never as a silent hole.

### 2026-10-07 · Reading per kind of match (#331)
- Settings → Reading has two choices now: how the chat is read during Competitive, and during every other match. "Live, light" (Windows OCR) costs your game almost nothing; "Live, best quality" is RapidOCR.
- Competitive reads light from now on; other matches stay on best quality. Between matches the chat is always read with the best quality.
- If you had switched to Windows OCR by hand, every match now reads light, and between matches it's RapidOCR again.

### 2026-10-06 · Umlaut runs (#322)
- Behind the scenes: long umlaut runs like "täääät" stay as they are for v1; they don't come up in real chat.

### 2026-10-06 · Lighter chat reading (#115)
- Reading the chat takes about a third less CPU: YapTracker finds the lines on a smaller copy of the chat box and still reads each line at full size.

### 2026-10-06 · New season's map (#318)
- The new map Watchpoint: Grimsvotn is known by name, so its matches show it in Sessions.

### 2026-10-06 · Gentler on Windows 10 (#319)
- On Windows 10, YapTracker copies from the screen far less often: the chat box twice a second instead of 4 times (once a second while the chat doesn't change), and the match screens in 4 pieces instead of 7. The game waits for each copy, so it waits much less.

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
- Stretched words keep every umlaut too: "täääätüüüütatäääää" now reads exactly as written.

### 2026-10-04 · Callouts read right (#290)
- Callouts are written as the comms wheel says them: "Eall back!" becomes Fall back!, "Enemy llari!" Enemy Illari!, and pieces like "My" or "/ Enemy" are no longer lines of their own.
- A callout read once with a garbled name is the same line as the clear one, not a second yap.

### 2026-10-04 · Callouts out of the way (#289)
- Live and match transcripts hide comms-wheel callouts ("Group up!", "Enemy Sombra!") by default, so the chat is what people wrote. The Callouts switch next to the channel names shows them again, with a count of how many are hidden.

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
- "Look who's back!": a card pops up when someone you've met before writes in chat.
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
