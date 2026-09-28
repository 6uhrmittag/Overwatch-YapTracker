# YapTracker 🗨️

**Remember who you played Overwatch with — and what they said.**

YapTracker reads Overwatch's text chat from the screen, keeps a local log of every
message, and lets you keep notes and a verdict on the people you meet. When
someone you already know types in chat, YapTracker shows you who they are, when
you last played together, and what you wrote about them — so you can say hi.

> 🚧 **Work in progress.** Follow the pinned 🗺️ Roadmap issue for progress.

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

Setup, calibration and hotkeys will be documented here for v1.0.

## Privacy

Chat logs contain other players' names and messages. They are stored only on your
PC (`%LOCALAPPDATA%\YapTracker\data`) and never uploaded anywhere.

## Development

Built with Claude Code — see [`CLAUDE.md`](CLAUDE.md) for the project brief, rules
and scope.
