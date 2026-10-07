# YapTracker UI guide

**Every UI issue follows this file.** If something here is unclear, pick the
option that matches the mockups in `docs/ui/mockup/` and note it under
"Decisions I made".

Mockup sources (HTML with inline styles — read them for exact values):

| File | Screen |
|---|---|
| `docs/ui/mockup/Live.dc.html` | Live view during a match, with familiar-face cards |
| `docs/ui/mockup/Profile.dc.html` | Player profile: verdict stickers, yap-o-meter, notes, their yaps |
| `docs/ui/mockup/Setup.dc.html` | First start: draw the chat box |
| `docs/ui/mockup/Kit.dc.html` | Colours, type, buttons, stickers, voice |

(They're design-canvas files: `<x-dc>`, `{{holes}}` and `<sc-for>` are canvas
syntax. Translate the markup and inline styles to NiceGUI; don't try to run them.)

---

## The one rule

> **Silly lives in words, colours and motion. The layout stays boring.**

Structure is predictable: icon rail on the left, one content area, cards.
The fun is in the copy, the stickers, the tilt and the bounce — never in
unexpected layouts, hidden controls or clever navigation.

## Simple

- **Live is the only screen needed during play.** Everything else is for
  between matches.
- **Queue test:** every action takes < 10 seconds and ≤ 2 clicks.
- **Glanceable:** body text ≥ 15 px, names ≥ 16 px bold, the familiar-face card
  name ≥ 36 px. It sits on a second monitor and is read out of the corner of an eye.
- **No settings needed after first start.** The setup wizard (Setup mockup)
  handles calibration; defaults for everything else.
- **Hotkeys are shown next to the buttons they trigger** (keycap chips).
- **Works from 720 px wide; tested at half of a 1920 screen** (next to OverLooker, #226). Never a
  horizontal scrollbar: below 1100 px Live is one column (newest familiar face on top), text cuts
  with an ellipsis or wraps as whole words.

## Self-explaining

There is no user guide: the app *is* the guide, plus a short README quick start.
So every screen has to answer "what is this and what do I do?" on its own.

- **Every empty view says what will appear and when.** "Play a match and the
  people who yap will show up here." Never a blank card.
- **Every setting has a one-line hint** underneath: what it changes and when
  you'd touch it. If you can't write the hint, the setting probably shouldn't exist.
- **Every state is visible.** Listening, paused, waiting for Overwatch, recording
  lost: always shown in words on Live, never only as a colour or an icon.
- **Errors say what to do next,** not what broke. "Overwatch isn't in borderless
  windowed — switch it in Video settings" beats "Capture failed".
- **Nothing is only reachable by hotkey.** Every hotkey has a visible button
  (with its keycap chip).
- **Icons in the rail and icon-only buttons have a tooltip** with the plain word.
- **No feature needs a manual.** If a PR needs a paragraph of explanation for the
  user, the UI isn't done yet: add a hint, better copy, or a sensible default.

## Colours

| Token | Hex | Use |
|---|---|---|
| `night` | `#0d1016` | Window chrome, icon rail |
| `ground` | `#12151c` | Page background |
| `panel` | `#1a1f29` | Cards, sections |
| `panel-raised` | `#1f2530` | Familiar-face cards |
| `panel-inset` | `#151a22` | Quotes, message bubbles inside cards |
| `line` | `#252b38` | Card borders |
| `line-strong` | `#343c4d` | Inputs, secondary buttons |
| `text` | `#f2f4f8` | Main text |
| `text-soft` | `#c3cad8` | Secondary text on panels |
| `muted` | `#9aa3b5` | Meta info, labels |
| `faint` | `#6f788c` | Timestamps, hints |
| `accent` | `#ff9c2a` | "Payload orange": active nav, primary buttons, banners |
| `accent-shadow` | `#b86a10` | Hard shadow under orange elements |
| `ok` | `#7ce38b` | Listening, saved |
| `danger` | `#ff5c66` | Nope, errors |

**Chat channels:** Team `#5cc3ff` · Match `#ffae4d` · Group `#7ce38b` ·
System `#8a93a6` (italic). Channel colour goes on the channel label and the
speaker name; message text stays `text`.

## Verdict stickers

Stored values stay `friend / fun / neutral / avoid`. The UI says:

| Stored | Label | Fill | Ink | Icon | Tilt |
|---|---|---|---|---|---|
| `friend` | **Bestie** | `#ffc83d` | `#2a1d00` | heart | −5° |
| `fun` | **Fun** | `#b98cff` | `#1d0b3a` | star | +3° |
| `neutral` | **Meh** | `#7d8699` | `#12151c` | flat face | −2° |
| `avoid` | **Nope** | `#ff5c66` | `#2b0508` | no-entry | +4° |

Pill shape, 2 px ink-coloured border, uppercase 800 weight, hard shadow
`0 3px 0 rgba(0,0,0,.45)`, always slightly tilted. Icons are inline SVG —
**no emoji anywhere in the UI** (they render inconsistently in WebView2).

## Type

- **Display:** Barlow Condensed 800 italic, uppercase — headings, player names,
  banners ("LOOK WHO'S BACK!"). Google Fonts, open license; bundle the font files
  with the app (no network at runtime).
- **Body:** Nunito Sans 400/600/700/800 — chat, notes, buttons, everything read.
- Tabular numbers everywhere (`font-variant-numeric: tabular-nums`).
- Never Blizzard's fonts, logos, hero art or icons.

## Shapes & motion

- Radius: 12–14 px for buttons/inputs, 16–20 px for cards, pills for stickers.
- **Arcade buttons:** ≥ 44 px tall, hard bottom shadow (`0 4px 0 accent-shadow`
  for primary, `0 3px 0 #0b0d12` for secondary). Pressed: shadow gone, moved
  down 3 px.
- App logo: orange rounded square tilted −6°, speech bubble icon.
- Motion is short and snappy (≤ 450 ms): cards pop in with a small overshoot,
  the "Listening" dot pulses, the calibration box has marching ants.
  Respect `prefers-reduced-motion`.

## Components (see mockups)

- **Icon rail:** 76 px wide, 52 px targets, active item = orange filled
  rounded square. Items: Live · Yappers · Sessions · Search · Settings (bottom).
- **Status pill:** Listening (green, pulsing) · Paused (orange) · Waiting for
  Overwatch (muted). While listening it names the match (#268): *In a match*
  (map · mode · time) · *Match over* (result, for the 90 s of post-match chat) ·
  *Between matches* ("the next match starts by itself at hero select"). The chat
  card says *Last match* after the result, until the next one starts.
- **Chat line:** time · channel · speaker (bold, channel colour) · text. Known
  players get a 3 px underline in their verdict colour and a faint gold row tint.
- **Familiar-face card** (the loudest thing in the app): orange banner
  "LOOK WHO'S BACK!", name ≥ 36 px, verdict sticker, "Last seen … · N matches
  together · N yaps", first line of notes as a quote, buttons *Open profile* /
  *Got it*. Avoid-verdict players get a compact card with a red border instead
  of the banner. New cards stack on top; they fade after ~2 minutes.
- **Keycap chip:** small dark rounded label, e.g. `Ctrl Alt F`. Only shown when the user set that hotkey: none are set by default (#328).
- **Yap-o-meter:** striped orange bar, levels *Silent type · Casual yapper ·
  Certified yapper · Yap lord* (by yaps per match, thresholds are a detail).

## Vocabulary

| In the UI | In code / DB |
|---|---|
| yap(s) | chat message(s) |
| yapper(s) | player(s) |
| Yappers (nav) | Players view |
| verdict stickers Bestie/Fun/Meh/Nope | `friend/fun/neutral/avoid` |
| "Look who's back!" | familiar-face card |
| "Who's that?" | quick lookup |

## Voice

Short, warm, a little cheeky. Never mean about players, never blames the user.

| Situation | Copy |
|---|---|
| No chat yet | No yaps yet. Suspiciously quiet lobby. |
| Listening, nobody typing | Ears open. Nobody's typing right now. |
| Game not running | Waiting for Overwatch. I'll be right here. |
| Paused | Ears covered. Nothing is being saved. |
| Lookup, no match | Never met them. Want to add them? |
| Notes saved | Saved (with check icon) |
| Calibration hint | Be generous — a bit too big is fine. |

## Every UI PR

Includes a screenshot of the changed screen in the PR body. Compare against
the mockup before opening the PR, and check the **Self-explaining** rules above:
empty state, hints, visible state, no hotkey-only actions.
