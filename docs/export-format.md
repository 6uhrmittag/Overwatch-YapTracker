# YapTracker export format

**Settings → Export → Export everything** writes `Documents\YapTracker\export-<date>\yaptracker-export.json` (`export-<date>-anonymized` with **Anonymize names**), with everything YapTracker collected: sessions, matches, every chat message, your yappers and the times nothing was recorded. It's meant for your own scripts, spreadsheets and other tools.

- **Your data is yours.** Do with an export whatever you like.
- **The format is free to use** (MIT, like the rest of YapTracker). Read it, write it, build on it; no need to ask.
- The JSON Schema is [`export.schema.json`](export.schema.json). Every export YapTracker's tests make is checked against it.
- Other players' names are in there, as read from chat. Think before you publish one, or switch on **Anonymize names**.

## Basics

- UTF-8 JSON, one file, pretty-printed.
- Times are ISO 8601 with your PC's UTC offset, to the second: `2026-10-01T20:05:12+02:00`.
- Ids (`sessions[].id`, `matches[].id`, `messages[].id`, `players[].id`) are the database ids. They never change, so two exports can be diffed or merged by id.
- `format` is always `"yaptracker-export"`; `format_version` is `1`. A change that could break a reader gets a new version; new optional fields don't.

## Top level

| Field | |
|---|---|
| `format`, `format_version` | `"yaptracker-export"`, `1` |
| `exported_at` | when the export was made |
| `app_version` | the YapTracker that made it, e.g. `0.4.160` |
| `anonymized` | `false`: names are as read. `true`: every name is a pseudonym like `Player-7f3a` (the same in every file of this export, random per export), also inside the text (as whole words, the names read in the same match); your notes and the other spellings are left out |
| `sessions` | evenings of play, oldest first, each with its `matches` and their `messages` |
| `messages_outside_matches` | chat read while no match was running (rare) |
| `players` | everyone you met: verdict, notes, spellings, counts |
| `capture_gaps` | time spans that weren't recorded, and why |

## sessions[]

| Field | |
|---|---|
| `id` | |
| `started_at`, `ended_at` | `ended_at` is `null` while the session runs (or if YapTracker never saw its end) |
| `matches` | in play order |

## matches[]

| Field | |
|---|---|
| `id` | |
| `number` | 1 for the first match of its session |
| `started_at`, `ended_at` | `ended_at` is `null` if no end was seen |
| `outcome` | `victory`, `defeat`, `draw` or `null` |
| `map`, `mode` | as Overwatch shows them on the hero-select screen, e.g. `ESPERANÇA` and `UNRANKED` (the queue), or `null` |
| `detected_by` | how the start was found: `heroselect` (the "Assemble your team" screen), `endscreen` (first chat after the last match's end), `gap` (first chat after a long quiet), `hotkey` (Ctrl+Alt+M) |
| `incomplete` | `true` if a capture gap overlaps the match: some chat may be missing |
| `messages` | oldest first |

## messages[]

| Field | |
|---|---|
| `id` | |
| `time` | when it was read |
| `channel` | `team`, `match`, `group`, `system` or `unknown` (the colour didn't tell) |
| `speaker` | the name as read (`null` when there was none) |
| `player_id` | the yapper it belongs to (`players[].id`), or `null` |
| `role` | `me` (your own line), `crew` (your crew) or `null` |
| `hero` | from team comms lines like `Name (Lúcio): Group up!`, else `null` |
| `text` | what was said. An emoji or icon OCR couldn't spell is `◇` |
| `ocr_confidence` | 0–1, or `null`. Windows OCR always reports 1.0 |
| `flagged` | `overwatch` (Overwatch showed a `[Report]` link), `manual` (you marked it spicy) or `null` |
| `has_glyphs` | `true` if the text contains a `◇` |
| `picture` | only with **Line pictures**: the line as it looked in Overwatch, e.g. `line-images/123.webp` |

## players[]

| Field | |
|---|---|
| `id` | |
| `display_name` | the spelling read most often |
| `verdict` | `friend` (Bestie), `fun`, `neutral` (Meh), `avoid` (Nope) or `null` |
| `notes` | your notes, as typed |
| `first_met`, `last_met` | |
| `aliases` | other spellings that were read as this player |
| `matches`, `messages`, `callouts`, `flagged_messages` | matches together, lines typed, comms-wheel callouts ("Enemy Sombra!"), spicy lines |

## capture_gaps[]

| Field | |
|---|---|
| `started_at`, `ended_at` | `ended_at` is `null` for a gap that is still open |
| `reason` | `crash` (capture stopped), `no_frames` (no picture from Overwatch), `window_lost`, `paused`, `app_not_running` (Overwatch ran without YapTracker) |

## The other files

With **Markdown too** (on by default), the folder also has `README.md` (what's inside, counts, date range), `sessions/<date>-session-<id>.md` (one file per evening: every match with its chat, and where nothing was recorded) and `players.md` (your yappers). With **Line pictures**, `line-images/<message id>.webp` holds each line as it looked; they're never included in an anonymized export, because they show the names.

`players.json` from **Export yappers** holds the same `players` records with `format: "yaptracker-players"`.
