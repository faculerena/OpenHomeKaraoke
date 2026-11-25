---
name: OpenHomeKaraoke
description: The house's own console radio, tuned to tonight.
colors:
  ground: "#1d1410"
  cab: "#261a13"
  cab-2: "#31211a"
  line: "#4a3326"
  print: "#f1e3c4"
  dim: "#c4ad8e"
  faint: "#a08a6d"
  amber: "#f2b544"
  amber-hover: "#f6c566"
  amber-ink: "#2a1a0c"
  needle: "#d9472f"
  eye: "#6fc39f"
  warn: "#f2b544"
  bad: "#ef6a52"
  bad-ink: "#ffc4b8"
  glass-off: "#170f0b"
  glass-warm: "#6a4512"
  glass-mid: "#3d2711"
  glass-edge: "#1f150d"
  singer-sky: "#9fd0f0"
  singer-rose: "#e9a6c9"
  singer-lime: "#b9d98a"
  singer-apricot: "#f0a77a"
  singer-lilac: "#c6b3f5"
  singer-mint: "#8fd6c8"
  singer-butter: "#f5d77a"
  singer-coral: "#f28b82"
typography:
  display:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "44px"
    fontWeight: 500
    lineHeight: 1.02
    letterSpacing: "-0.005em"
  headline:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "0.01em"
  title:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: "0.01em"
  readout:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.04em"
    fontFeature: "\"tnum\""
  body:
    fontFamily: "Barlow, Noto Sans, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: "Barlow, Noto Sans, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  band-heading:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.16em"
  label:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.1em"
  scale-print:
    fontFamily: "Barlow Condensed, Barlow, Noto Sans CJK JP, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0.08em"
rounded:
  tick: "2px"
  check: "6px"
  plate: "8px"
  field: "10px"
  glass: "12px"
  cabinet: "18px"
  popup: "20px"
  pill: "999px"
spacing:
  gutter: "clamp(16px, 4vw, 48px)"
  row: "12px"
  band-gap-y: "40px"
  band-gap-x: "56px"
  dial-top: "28px"
components:
  button-primary:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.amber-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "9px 18px"
  button-primary-hover:
    backgroundColor: "{colors.amber-hover}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.print}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "9px 18px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.bad}"
    rounded: "{rounded.pill}"
    padding: "9px 18px"
  button-phone:
    rounded: "{rounded.pill}"
    padding: "0 20px"
    height: "44px"
  text-action:
    backgroundColor: "transparent"
    textColor: "{colors.faint}"
    padding: "4px 2px"
  band-selector:
    backgroundColor: "{colors.cab}"
    rounded: "{rounded.pill}"
    padding: "4px"
  band-selector-live:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.pill}"
    padding: "8px 16px"
  chip:
    backgroundColor: "{colors.cab}"
    textColor: "{colors.dim}"
    rounded: "{rounded.pill}"
    padding: "7px 13px"
  chip-on:
    backgroundColor: "{colors.cab-2}"
    textColor: "{colors.print}"
  field:
    backgroundColor: "{colors.cab-2}"
    textColor: "{colors.print}"
    typography: "{typography.body}"
    rounded: "{rounded.field}"
    padding: "10px 12px"
  field-phone:
    backgroundColor: "{colors.cab-2}"
    textColor: "{colors.print}"
    rounded: "{rounded.glass}"
    height: "48px"
  dial-cabinet:
    backgroundColor: "{colors.cab}"
    rounded: "{rounded.cabinet}"
    padding: "24px clamp(16px, 2.4vw, 32px) 26px"
  dial-glass:
    backgroundColor: "{colors.glass-off}"
    rounded: "{rounded.glass}"
    height: "150px"
  dial-glass-phone:
    rounded: "{rounded.glass}"
    height: "112px"
  dial-needle:
    backgroundColor: "{colors.needle}"
    rounded: "{rounded.tick}"
    width: "3px"
  magic-eye:
    rounded: "{rounded.pill}"
    size: "18px"
  qr-plate:
    backgroundColor: "{colors.print}"
    rounded: "{rounded.plate}"
    padding: "8px"
  popup:
    backgroundColor: "{colors.cab}"
    textColor: "{colors.print}"
    rounded: "{rounded.popup}"
    padding: "26px 22px 20px"
---

# Design System: OpenHomeKaraoke

## Overview

**Creative North Star: "Radio de living"**

The house's own console radio, tuned to tonight. Both surfaces, the host's admin panel and the guests' phone site, are the front of one walnut cabinet radio in a dim living room at night. The ground is a flat walnut tint (never woodgrain). Cabinet bands sit one step lighter, and text is printed in cream like the lettering on a dial. The one lit thing is the backlit amber glass of the tuning dial, with a red needle across it. Health shows as magic-eye tubes, green when a service is fine and a dark dead tube when it is off.

Density is calm and readable at arm's length. Type scale and space carry the hierarchy, never containers. Sections are bands separated by 1px rules, and rows share one baseline. Labels and numerals use condensed dial-scale caps. Reading text uses a warm workhorse sans. Each singer owns one fixed dial colour everywhere they appear, so a name is recognisable at a glance across the panel, the phone and the dial.

The system rejects two things: the boxed dark dashboard (card grids, KPI tiles, nested panels) and the neon karaoke bar (glows, saturated gradients, arcade type). It is dark because of the scene, not as a style choice: no large bright surface may blind a room whose lights are off.

**Key Characteristics:**
- Flat walnut ground with cabinet bands one tonal step up, ruled by 1px lines.
- Backlit amber glass is the only lit surface, made with a radial gradient, never a glow shadow.
- Tonight's dial is the signature: a sideways-scrolling tuning scale where the needle is now and songs are stations.
- One fixed 8-colour singer palette, hashed from the name, shared by both surfaces.
- Condensed caps for labels, numerals and buttons. Barlow sans for reading.
- Pill controls, quiet text actions, and no elevation.

## Colors

A low, warm palette of walnut and cream, lit by a single amber, with a red needle, a tube green and eight soft singer hues.

### Primary
- **Dial Amber** (amber): the backlit glass and everything that means "the radio is on or this is yours to press". Primary pill fill, the live band in the band selector, the clock readout, links, the focus ring, the caret, text selection, the active lyric line, the active tab underline and the phone's active nav item. It brightens to **Warm Bulb** (amber-hover) on hover.
- **Amber Ink** (amber-ink): text on amber fills. Never use cream on amber.

### Secondary
- **Needle Red** (needle): the dial needle, the phone's range-slider thumb, and the "hot" song badge. Nothing else.

### Tertiary
- **Magic-Eye Green** (eye): healthy. Used for the "ok" eye, done jobs, good badges and success text.
- **Warn Amber** (warn): starting, stopping and degraded states, plus counts that need action. It has the same value as Dial Amber on purpose: needing attention is the light coming on.
- **Fault Coral** (bad): failed services, danger actions (as text and a half-alpha outline, never a fill) and error text. Error message text on a tinted coral band uses **Fault Blush** (bad-ink).

### Neutral
- **Walnut Ground** (ground): the page, the sticky top bar, and the phone's full-bleed #container band.
- **Cabinet** (cab): the dial cabinet, popups, the band selector track, chips, the phone's open navbar menu, and file wells.
- **Cabinet Inset** (cab-2): controls set into the cabinet, such as fields, selected chips and bands, the phone's dark buttons, menus and table-row hover.
- **Rule** (line): every 1px divider, secondary pill outlines, scrollbar thumbs and inset selection rings.
- **Dial Print** (print): primary text, and the QR plate.
- **Aged Print** (dim): secondary text, such as meta lines, the subtitle under the current song and unselected band text.
- **Faded Print** (faint): tertiary text, such as band headings, row actions at rest, hints, placeholders and inactive tabs.

### Glass
- **Glass Off** (glass-off): the panel glass while the radio is off, a flat near-black.
- **Lit Glass** (glass-warm, glass-mid, glass-edge): the stops of the lit glass, `radial-gradient(130% 160% at 35% 125%, glass-warm 0%, glass-mid 42%, glass-edge 100%)`. The phone glass is always lit.

### Singers
Eight soft hues (singer-sky, singer-rose, singer-lime, singer-apricot, singer-lilac, singer-mint, singer-butter, singer-coral). The singer's name is reduced to a 31-multiplier string hash, and the hash modulo 8 picks the colour, so the same singer gets the same colour on the panel and the phone. They colour singer names, the dial segments' left edge and bar, and the "who" column in queues.

### Named Rules
**The One Light Rule.** Amber glass is the only lit surface on the page. Light comes from a background gradient, never from a glow shadow. Indicators (the eyes, the needle, singer colour) are small and are not light sources.

**The Same Singer Rule.** A singer's colour comes only from the shared 8-colour palette, through the name hash. Never assign singer colours by position, by role or by hand.

**The Ink On Amber Rule.** Anything filled with amber carries Amber Ink text.

## Typography

**Display Font:** Barlow Condensed (with Barlow, Noto Sans CJK JP, system-ui)
**Body Font:** Barlow (with Noto Sans, Noto Sans CJK JP, system-ui)

**Character:** The condensed face is the lettering printed on the dial and the cabinet: tracked caps for labels, tall numerals for the clock. Barlow is the warm, plain voice for song titles in rows, meta lines and settings. Both faces are self-hosted (OFL) in weights 400, 500 and 600 so the panel works offline. The phone ships Condensed in 500 and 600 only.

The scale is a strict seven steps, `--t1` to `--t7`: 13, 15, 17, 20, 26, 34 and 44px. No other sizes are used for type. The phone stops at `--t6`.

### Hierarchy
- **Display** (Condensed 500, 44px, 1.02): the current song title in the panel dial head, set with balanced wrapping. It drops to 34px under 760px.
- **Headline** (Condensed 500, 34px, 1.1): panel sheet headings in Library and Settings, the phone's page titles, and the phone's now-playing title.
- **Readout** (Condensed 500, 26px, tabular numerals, amber): the dial clock and position.
- **Title** (Condensed 500, 20px, 1.25): song names in the library list and the phone's lyrics title. One-line summaries use the same size at 1.4.
- **Body** (Barlow 400, 17px, 1.5): the default text. Row names use weight 500 at 1.3. Explanatory paragraphs are capped at 68ch.
- **Body Small** (Barlow 400, 15px): meta lines, hints in rows and Up next counts.
- **Band Heading** (Condensed 600, 15px, 0.16em tracking, uppercase, faint): the heading of each band, such as "The set", "Up next" and "Join", and the phone's h3.
- **Label** (Condensed 500–600, 13–15px, 0.06–0.1em tracking, uppercase): buttons, chips, tabs, field labels, badges, the singer "who" column and quiet text actions.
- **Scale Print** (Condensed 500, 13px, 0.08em): the clock-time numerals on the dial. Quarter hours are full print at weight 600, and other minutes are print at 72% alpha.

### Named Rules
**The Seven Steps Rule.** Type sizes come only from `--t1` to `--t7`. Hierarchy is made by jumping steps and by space, never by boxing.

**The Dial Print Rule.** Uppercase tracked lettering is for labels, numerals, buttons and band headings only. Song titles and sentences are never in caps.

**The Tabular Numbers Rule.** Clock times, counts and positions use tabular numerals so the readout doesn't jitter as it ticks.

## Layout

The page is a stack of full-width bands inside one gutter of `clamp(16px, 4vw, 48px)`. On the panel, a sticky top bar (the brand, the tabs, and the band selector with power, ruled underneath) sits over the dial cabinet (28px down). Under the dial, the bands run in an auto-fit grid of columns at least 300px wide, with gaps of 40px vertical and 56px horizontal. They reflow by whole cells, never by squeezing. Library and settings are sheets 32px apart, 48px between consecutive sheets, and also use auto-fit grids (minimum 320px for splits, 240px for settings fields).

Rows (services, queue, songs and batches) are grids on one baseline, with a 28px lead column for an eye or position number, a flexible middle and an auto actions column. Each row carries a 1px top rule and 11–13px of vertical padding. Counts are one condensed summary line ("90 songs · 3 need lyrics"). Only the part needing action turns Warn Amber at weight 600.

On the phone, the #container is a full-bleed Walnut Ground band with 22px/18px padding and a 110px bottom gutter. Bulma boxes inside it lose their fill and radius and become ruled sections, with a 1px top line and 18px top padding. The dial strip sits at the top of Home, with the big controls under it.

One breakpoint at 760px. Below it, the band selector and power buttons go full width with flex-split targets, the display title steps down to 34px, song rows stack with their actions left-aligned, and the glass is 140px tall.

**The Band Not Box Rule.** Content sections are bands separated by 1px rules, never boxed cards. Filled rounded surfaces are reserved for the dial cabinet, popups, the welcome preview and inset wells (file lists, fields), and they never nest.

**The One Line Count Rule.** There are no KPI tiles. A count is one line of dial print, emphasised only where it needs action.

## Elevation & Depth

The system is flat. There are no elevation shadows anywhere. Depth is tonal: Ground, then Cabinet, then Cabinet Inset, with each control one step lighter than what it is set into. Selected states use a 1px inset ring (Rule, or Amber on a selected chip) instead of a lift. The phone's navbar and every Bulma box have their shadows removed. Light is not depth either: the lit glass is a radial background gradient, warm low in the frame as if a bulb sits behind the bottom-left of the scale. Popups float over a near-black overlay at 82% opacity, not on a shadow.

### Shadow Vocabulary
- **Selection ring** (`box-shadow: inset 0 0 0 1px var(--line)`): the selected band button, the phone's secondary popup button, and the phone's control well.
- **Chip-on ring** (`box-shadow: inset 0 0 0 1px var(--amber)`): the selected filter chip.
- **Nav underline** (`box-shadow: inset 0 -3px 0 var(--amber)`): the phone's active navbar item.
- **Label lift** (`text-shadow: 0 1px 2px rgba(0,0,0,.6)`): text on dial segments only, for legibility over the glass.

**The No Glow Rule.** Nothing casts light. A shadow is only an inset ring or the dial's legibility text-shadow, and is never an outer glow or a drop shadow.

## Shapes

Shapes are soft and radio-like. Every control is a pill (999px): buttons, chips, the band selector and its buttons. Surfaces have generous rounding: the cabinet is 18px, popups are 20px and the glass is 12px. Fields are 10px on the panel and 12px on the phone, and file wells are 10px. Small marks: QR plates are 8px, phone checkboxes 6px, and the needle and slider thumb 2–4px. The magic eyes and badge dots are circles. Dial segments are open forms: a 2px left edge in the singer's colour, with a 4px bar along the bottom (55% alpha, rounded on its right end). Dividers are hairlines (1px), and there are no heavier borders.

## Components

### Buttons
Soft, confident pills in condensed caps.
- **Shape:** fully rounded pill (999px).
- **Primary:** Dial Amber fill, Amber Ink text, Condensed 600 at 15px, 0.1em tracking, uppercase (9px 18px padding). Hover brightens to Warm Bulb.
- **Secondary:** transparent with a 1px Rule outline and print text. Hover lifts the outline to Aged Print.
- **Danger:** Fault Coral text with a half-alpha coral outline, never a fill.
- **Small:** 6px 12px at 13px.
- **Disabled:** 40% opacity.
- **Phone:** the same treatment over Bulma, with a 44px minimum height (36px small). Popup actions are 48–52px tall, with the primary first and the second outlined. Every Bulma colour variant (warning, primary, success, info, link) maps to the amber primary.
- **Focus:** a 2px amber outline, 2px offset, on every focusable element.

### Text actions
Quiet, condensed caps (13px, 0.1em, faint) with no chrome, used for row actions such as panel log, rename or delete. Hover turns them to print. Danger text actions are coral. Use them for anything a row offers; keep pills for the primary and secondary actions of a band or popup.

### Band selector
A Cabinet pill track (4px padding) holding pill buttons in Aged Print. The selected band sits in Cabinet Inset with a Rule ring. When the selected band is live, it fills with amber and Amber Ink text. Colour transitions run 0.25s on `--ease`.

### Chips
- **Style:** a Cabinet pill with Aged Print condensed caps (7px 13px). The count after the label is faint.
- **State:** "on" moves to Cabinet Inset with print text and an amber inset ring.

### Cards / Containers
- **Corner Style:** cabinet 18px and popups 20px. Everything else is a ruled band, not a container.
- **Background:** Cabinet on Walnut Ground. Insets inside a cabinet are Cabinet Inset.
- **Shadow Strategy:** none (see Elevation & Depth).
- **Border:** none on filled surfaces. Bands use a 1px Rule top line.
- **Internal Padding:** the cabinet is 24px by clamp(16px, 2.4vw, 32px), and popups are 26px 22px 20px.

### Inputs / Fields
- **Style:** a Cabinet Inset fill with a transparent 1px border, print text in Barlow 17px, and faint placeholders. The panel uses 10px rounding (10px 12px padding). The phone uses 12px rounding with a 48px minimum height. Selects draw their own chevron in Aged Print on the panel and amber on the phone.
- **Focus:** the border turns amber.
- **Checkboxes:** the panel uses `accent-color: amber` at 16px. The phone draws a 20px Cabinet Inset square (6px rounding, Rule border) that fills amber when checked, with an Amber Ink tick.
- **Range sliders (phone):** a 6px amber track fading from 50% to 20% alpha, with an 8 by 28px Needle Red thumb. The needle is the thumb.
- **Labels:** condensed caps at 15px, faint, stacked over the field.

### Navigation
- **Panel:** a sticky Walnut Ground top bar with a 1px rule. The brand is an inline SVG mark with Condensed 600 caps. Tabs are condensed caps in faint, dim on hover, and print with a 2px amber underline when active.
- **Phone:** a 60px Walnut Ground navbar with a 1px rule and no shadow. Items are faint with 48px minimum targets, and the active item is amber with a 3px inset amber underline. The burger menu opens as a Cabinet sheet with 52px rows.

### Magic-eye indicator
An 18px circle drawn as a radial gradient, used as the lead mark of each service row.
- **Ok:** a pale core into Magic-Eye Green, fading to a deep green rim.
- **Starting / Stopping:** the same gradient in Warn Amber, pulsing to 45% opacity over 1.6s.
- **Degraded:** the same amber gradient, steady.
- **Failed:** the same gradient in Fault Coral.
- **Stopped:** a dark tube, brown core to near-black.

This is panel-only.

### QR plate
Join codes sit on a Dial Print plate (8px rounding, 8px padding, at most 132px wide), with the QR image blended by `multiply` so its white becomes cream. These plates are the only cream surfaces, and they are kept small.

### Tonight's dial (signature)
A sideways-scrollable tuning scale on backlit amber glass.
- **Glass:** 12px rounding, scrolling horizontally only, with horizontal overscroll contained. It is 150px tall on the panel (140px under 760px) and 112px on the phone, where the scrollbar is hidden. On the panel it is Glass Off while the radio is off, and turns to the Lit Glass gradient (the warm-up) when the radio turns on.
- **Scale:** minute ticks (2px, print at 75% alpha) and quarter-minute ticks (1px, print at 30–32% alpha) drawn with two repeating linear gradients spaced by `--min`. A lit span fades from transparent to amber at 28–30% alpha, from the start up to now.
- **Needle:** a 3px Needle Red bar with 2px rounding at now. It sits behind the song segments and their labels, and moves linearly (0.5s per step).
- **Segments:** one per song, in the singer's colour, with the title in Barlow 13px over the singer name in Condensed 600 caps, both carrying the label lift.
- **Panel:** a clock-time scale (24h labels, 120px per minute). It shows sung songs dimmed to 50% on the left, the current song at the needle, and queued songs as station marks at their estimated start times. Segments narrower than 70px keep only their colour bar. The glass follows the needle (holding it at 30% of the width) unless someone is browsing; a wheel, pointer, scroll or arrow key holds it for 8s. The mouse wheel scrolls sideways.
- **Phone:** the current song is the needle's span (70px per minute of the song). Queued songs follow as fixed-width stations (190px), because their lengths aren't known there. It follows the needle past 60% of the width, with the same 8s hold on touch or scroll.

Not yet reviewed: the panel's queued station marks and Up next rows have not been visually checked with a real queue.

### Motion
- **Warm-up:** the panel glass background and the scale opacity transition over 1.6s on `--ease` (`cubic-bezier(.16, 1, .3, 1)`) when the radio turns on.
- **Needle:** moves linearly.
- **Magic eye:** the starting and stopping eyes pulse.
- **Controls:** state colour changes take 0.2–0.25s.
- **Reduced motion:** prefers-reduced-motion zeroes every transition and animation on the panel, and stops the needle's transition on the phone.

## Do's and Don'ts

### Do:
- **Do** separate content sections with a 1px Rule line and let type steps and space carry the hierarchy.
- **Do** light the dial glass with its radial-gradient background, never with a shadow.
- **Do** colour every singer mention through the shared 8-colour palette and the name hash, on both surfaces.
- **Do** put Amber Ink on any amber fill, and keep amber for "on", "yours to press" and the focus ring.
- **Do** use quiet condensed-caps text actions for row actions, and amber or outlined pills for a band's primary and secondary actions.
- **Do** theme the browser's own surfaces: amber selection with ink text, Rule-coloured thin scrollbars, an amber caret, and a 2px amber focus ring with a 2px offset.
- **Do** show health with the magic-eye states (green ok, amber starting or degraded, coral failed, dark tube stopped).
- **Do** keep tap targets at 44px or more on the phone (48px fields, 48–52px popup actions).
- **Do** put any QR code or other must-be-light asset on a small cream plate with multiply blending.

### Don't:
- **Don't** box content sections as cards, nest a filled surface inside another, or build KPI tiles. A count is one line.
- **Don't** add glows, drop shadows or neon gradients. The only light is the amber glass.
- **Don't** introduce large bright surfaces. The room is dark.
- **Don't** use woodgrain or texture. Walnut is a flat tint.
- **Don't** set type outside the `--t1` to `--t7` steps, or put song titles and sentences in uppercase.
- **Don't** use Needle Red for anything but the needle, the slider thumb and the hot badge.
- **Don't** fill danger actions. Danger is coral text with a half-alpha outline.

## TV skins (exception)

The TV between songs (`lib/tv_skins.py`, drawn with pygame) does **not** use the Radio de
living world: it has six owner-chosen skins, picked in the panel (Settings, TV screen) and
switched live: Karaoke box, Guirnalda de cotillón, Afiche riso, Sleeve + band, Bare
essentials and Neón. They come from the 2026-11-25 direction board; the sketches are in
`.impeccable/mocks/decision/`. Shared rules, whatever the skin:

- A song is always named before the person who asked for it, never smaller than that name.
- The title is the panel's TV title, else the welcome title, else the app's name.
- The QR always has a light quiet zone and whole-pixel modules; every skin is checked to
  scan after a 720p QP 28 encode.
- The frame is static (the stream pays for it once), and its text comes from `lang/`
  (lines 241-245), so the TV language follows the panel's setting.
- Fonts are Fira Sans (OFL, in `font/`), with Arial Unicode and Unifont as fallbacks for
  other scripts; emoji are dropped.
- During a video song, the TV stream carries a scrolling bar: what's next (song · singer)
  and where to join. It is drawn into the stream (stream-tv.sh, ffmpeg drawtext, Noto Sans
  CJK) from text the app writes (karaoke.py `update_tv_bar`). It sits at the top, and moves
  to the bottom for songs whose lyrics sit at the top (Karaoke Mugen). It is a neutral dark
  bar in every skin, because the stream sets it up once at start and skins change live.
