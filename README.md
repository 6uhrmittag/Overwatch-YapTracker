# YapTracker 🗨️

**Remember who you played Overwatch with — and what they said.**

YapTracker reads Overwatch's text chat from the screen, keeps a local log of every message, and lets you keep notes and a verdict on the people you meet. When someone you already know types in chat, YapTracker shows you who they are, when you last played together, and what you wrote about them — so you can say hi.

![YapTracker's Live view: chat streaming in, and a "Look who's back!" card for a player met before](https://raw.githubusercontent.com/6uhrmittag/Overwatch-YapTracker/screenshots/readme-live.png)

> 🤖 **Disclaimer:** This project's code is 100% written by AI and driven by human ideas (plus a worrying number of Overwatch matches). Without AI it simply wouldn't exist — so take it or leave it. 💛

## What it is (and isn't)

- ✅ Chat log, player notes, verdicts, "Look who's back!" cards, "Who's that?" lookup, search, sessions with transcripts, exports, yap snaps
- ✅ 100% local: no account, no cloud, no telemetry
- ✅ Screen capture only (like OBS): no game memory access, no injection, no input to the game, no overlay on the game
- ❌ Not a stats or match tracker — use [OverLooker](https://overlooker.app/) for that

## Quick start

1. In Overwatch: **Options → Video → Display mode: Borderless Windowed**, and text chat switched on.
2. Install with the command under [Install & update](#install--update). Answer **Y** to "Start YapTracker with Windows?": from then on it waits quietly until Overwatch starts.
3. On first start, the setup walks you through three steps: it finds Overwatch, you drag a box around the chat, and you add your own name and your crew (the people you queue with).
4. Play. Chat appears in **Live**; when someone you've met before types, their card pops up. Nothing needs a key press.
5. Afterwards: **Yappers** for verdicts and notes, **Sessions** for the evening match by match, **Search** for that one line.

Everything else the app explains where you need it. This README is the only written guide.

## Install & update

Requirements: Windows 10/11, Overwatch in borderless windowed mode, text chat on.

One command installs the newest (pre-)release and later updates it. In PowerShell:

```
irm https://raw.githubusercontent.com/6uhrmittag/Overwatch-YapTracker/main/tools/update.ps1 -OutFile update.ps1
powershell -ExecutionPolicy Bypass -File update.ps1
```

The app goes to `%LOCALAPPDATA%\YapTracker\app` and is replaced on every update. Your data in `%LOCALAPPDATA%\YapTracker\data` is never touched. Run `update.ps1` again whenever you want the newest build; it closes YapTracker first and starts it again afterwards. `-Force` reinstalls, `-NoStart` skips the start.

### "Windows protected your PC" / Defender warnings

YapTracker isn't code-signed (a certificate costs money every year), so Windows doesn't know the file yet. On the first start SmartScreen may say **Windows protected your PC**: click **More info → Run anyway**. Defender occasionally flags apps packed with PyInstaller as suspicious, too. If you'd rather check before allowing it: the code is all here, and every release is built by [GitHub Actions](.github/workflows/ci.yml) from the commit it names, not on anyone's PC.

## Calibration

The setup asks you once to drag a box around the chat. Be generous: a bit too big is fine, too small misses long lines. "What I can read" next to it shows what YapTracker reads in that box, live.

![Drawing the chat box in the setup (demo picture, made-up names)](https://raw.githubusercontent.com/6uhrmittag/Overwatch-YapTracker/screenshots/readme-calibrate.png)

The box is kept as a share of the window, so it works at any resolution with the same aspect ratio. If Overwatch runs at a new size, Live shows a short hint; **Settings → Chat box → Calibrate** redraws it in a few seconds. Do it while Overwatch runs with chat visible (press Enter in the game if it faded).

## Hotkeys

Normal play needs none: capture, matches and sessions run by themselves. They're there for the odd correction and work anywhere in Windows, also in Overwatch.

| Default | What it does |
|---|---|
| `Ctrl+Alt+F` | YapTracker to the front, ready to type a name in **Who's that?** |
| `Ctrl+Alt+P` | Pause / resume; resumes by itself at the next match |
| `Ctrl+Alt+M` | New match, only if YapTracker missed a match start |
| `Ctrl+Alt+S` | Keep the last 20 s of chat as a debug sample |

Change them in **Settings → Hotkeys**: click **Change**, press the new keys. If another app already has a combo, Settings says so next to it.

## Your data

Everything lives in `%LOCALAPPDATA%\YapTracker\data` (**Settings → Your data → Open data folder**):

- `yaptracker.db`: the chat log, your yappers and notes (SQLite)
- `backups\`: a copy of the database every day (never during a match) and before every update of its format; the last 7 days plus one per week for 4 weeks
- `lines\`: the picture of every chat line, so emoji and icons OCR can't spell are kept (switch off in Settings if disk space is tight)
- `debug\`: chat moments YapTracker found hard, kept 14 days and 1 GB at most, to make reading better later (switch off in Settings)
- `logs\`: what the app did, for when something goes wrong

**Restoring a backup:** close YapTracker, copy the backup over `yaptracker.db` (keep the old file somewhere first, just in case), start YapTracker again.

**Exports:** **Settings → Export** writes your yappers as `players.md` and `players.json`, or everything (sessions, matches, messages, players, gaps) as one documented JSON file plus Markdown, optionally with anonymized names. The format is described in [`docs/export-format.md`](docs/export-format.md), with an example from a made-up evening in [`examples/export/`](examples/export/).

## Privacy

Chat logs, line pictures and debug samples contain other players' names and messages. They are stored only on your PC and never uploaded anywhere. The only network access is `update.ps1` fetching releases from GitHub. Yap snaps hide names by default, and exports can anonymize them.

## Known limits

- **Tested at** 2560×1440 and 3840×2160, the latter with Windows HDR on, on Windows 11 with an NVIDIA card. Other 16:9 sizes scale along; other aspect ratios need a calibration.
- **Windows 10** (and Windows 11 before 24H2) can't hand YapTracker just 4 frames a second; it would copy every frame the game draws. So there YapTracker copies only the chat box from the screen, 4 times a second, which costs about as little as on Windows 11 24H2. One difference: it reads what's on screen, so keep other windows off the chat box. **Settings → About** says which way your PC reads.
- **A black picture from the game window** (e.g. the game on the other graphics card): after a few seconds YapTracker reads the screen Overwatch is on instead, the same way, and says so in Live. It tries the window again at the next start. In exclusive Fullscreen the screen is black too: switch to Borderless Windowed.
- **Languages:** English and German chat are measured (umlauts and ß included). Other languages aren't tested; chat in other scripts (Cyrillic, Korean…) may come out wrong.
- **Emoji and game icons** show as `◇` in the text; click a line to see its picture.
- **Lines can be missed** when chat scrolls or fades faster than it's read (it's read every 1.5 s), e.g. a burst of many lines at once, or a very bright background behind the chat.
- **Group chat** gets its own channel once YapTracker has seen the `[Group]` chat box open once; until then those lines say "Chat".
- **Matches** start at hero select and end at VICTORY / DEFEAT. If one is missed, a quiet gap starts the next one; **New match** fixes the rest.
- **Only who typed:** players who never chat aren't logged (type their name in **Who's that?** to add them). No match stats, no full lobbies.
- **CPU:** reading chat costs about 16–18 % of one core over a 1440p recording, and an estimated 25 % at 4K. It always reads on the CPU, never on your graphics card: that's the game's. Whether YapTracker costs any FPS is still being measured.
- Windows only.

## License

MIT. Do whatever you like with it. Bundled fonts and libraries keep their own licenses, see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Development

Built with Claude Code — see [`CLAUDE.md`](CLAUDE.md) for the project brief, rules and scope, and the pinned 🗺️ Roadmap issue for progress.
