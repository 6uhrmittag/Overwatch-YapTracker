# YapTracker 🗨️

**Remember who you played Overwatch with — and what they said.**

YapTracker reads Overwatch's text chat from the screen, keeps a local log of every
message, and lets you keep notes and a verdict on the people you meet. When
someone you already know types in chat, YapTracker shows you who they are, when
you last played together, and what you wrote about them — so you can say hi.

> 🚧 **Work in progress.** Follow the pinned 🗺️ Roadmap issue for progress.
>
> 🤖 **Disclaimer:** This project's code is 100% written by AI and driven by human
> ideas (plus a worrying number of Overwatch matches). Without AI it simply wouldn't
> exist — so take it or leave it. 💛

## What it is (and isn't)

- ✅ Chat log, player notes, verdicts, "familiar face" alerts, search
- ✅ 100% local: no account, no cloud, no telemetry
- ✅ Screen capture only (like OBS) — no game memory access, no injection, no input
  to the game, no overlay on the game
- ❌ Not a stats or match tracker — use [OverLooker](https://overlooker.app/) for that

## Requirements

- Windows 10/11
- Overwatch in **borderless windowed** mode
- Text chat enabled in Overwatch

## Install & update

One command installs the newest (pre-)release and later updates it. In PowerShell:

```
irm https://raw.githubusercontent.com/6uhrmittag/Overwatch-YapTracker/main/tools/update.ps1 -OutFile update.ps1
powershell -ExecutionPolicy Bypass -File update.ps1
```

The app goes to `%LOCALAPPDATA%\YapTracker\app` and is replaced on every update. Your data in `%LOCALAPPDATA%\YapTracker\data` is never touched. Run `update.ps1` again whenever you want the newest build; it closes YapTracker first and starts it again afterwards. `-Force` reinstalls, `-NoStart` skips the start.

Setup, calibration and hotkeys will be documented here for v1.0.

## Privacy

Chat logs contain other players' names and messages. They are stored only on your
PC (`%LOCALAPPDATA%\YapTracker\data`) and never uploaded anywhere.

## Development

Built with Claude Code — see [`CLAUDE.md`](CLAUDE.md) for the project brief, rules
and scope.

Needs Python 3.12. From a fresh clone (WSL/Linux or Windows):

```
python3.12 -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[dev]
ruff check . && ruff format --check .
pytest
python -m yaptracker --version
```
