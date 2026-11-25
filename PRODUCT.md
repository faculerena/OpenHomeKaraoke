# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **The host** (the person whose machine this is). Starts, stops and checks on the karaoke
  from the admin panel: in a desktop app window on the karaoke PC, or from their phone over
  their tailnet. Also curates the song library (fixing, rebuilding lyrics, deleting).
- **Guests at a house party.** Use their own phones, through the browser, to search for and
  queue songs, follow lyrics, and control playback. They are Spanish speakers, of mixed ages
  and tech comfort, in a dim living room at night with the TV on, often a few drinks in:
  one-handed, distracted, not reading instructions.

## Product Purpose

A home karaoke machine that runs on one PC with a GPU. Guests pick any song (YouTube, YouTube
Music, Karaoke Mugen); the machine downloads it, separates the vocals, fetches real lyrics and
times them into a syllable color-wipe, and plays it on the TV. Success is a party where
anyone can get their song on screen in seconds without help from the host, and the host
never has to touch a terminal.

## Positioning

Turns any song into karaoke on the spot: GPU vocal separation plus real lyrics force-aligned
to the singer, at home and with no subscription. The video can go to a TV over the network
(HLS) or straight to the PC's own screen.

## Operating Context

- Phones join by scanning a QR code on the TV or opening a LAN URL. The https port is needed
  for voice search (the mic needs a secure context, self-signed certificate).
- The TV is a browser on the LAN (e.g. a laptop or TV Bro) showing the HLS stream, a couple
  of seconds behind live.
- The host's admin panel runs at :12345, reachable only from the machine and the host's own
  tailnet devices. It drives systemd user services: the voice/GPU server, the app (on this
  monitor or headless for the TV), and the Cloudflare tunnel for public mode.
- A first-visit welcome popup (editable from the panel) sets the house rules for the night.

## Capabilities and Constraints

- Guest UI: Flask/Jinja templates (`templates/`), currently Bulma, with i18n through
  `lang/` string tables. Search, queue, browse, lyrics panel (synced follow-along), pitch,
  speed, vocal mix (MUSIC / MIXED / VOICE), voice search, delays.
- Admin panel: one self-contained page (`panel/static/index.html`), vanilla JS, no external
  CDNs (must work offline), Overview and Library tabs.
- The project is a fork of upstream OpenHomeKaraoke and is meant to stay installable by
  someone else: party specifics (texts, hostnames) live in settings, not in the code.
- Phone UI must keep every existing element ID and JS hook working.

## Brand Commitments

- Name: OpenHomeKaraoke. The current logo (`logo.jpg`, a neon house with microphones) is
  **not** binding; the owner considers it ugly and it can be replaced.
- Guest-facing copy defaults to Spanish (rioplatense, informal "ustedes"), with English
  as the fallback for a shared install.

## Evidence on Hand

- A real library of ~90 songs (anime OPs from Karaoke Mugen, Argentine rock and pop,
  international pop), with color-wipe lyrics for all of them.
- No testimonials, user counts or press; none should be invented.

## Product Principles

1. **Nobody needs the host.** A guest who has never seen it can queue a song in under a
   minute.
2. **Forgiving in a dark, loud room.** Big targets, readable at arm's length, destructive or
   other people's actions hard to trigger by accident.
3. **The TV is the stage; phones are the remote.** The phone UI supports the singing and
   never competes with the screen.
4. **The host sees everything at a glance.** Health, who's singing, what the GPU is doing,
   without reading logs.
5. **Personal by configuration, generic by default.** Party flavor comes from settings.

## Accessibility & Inclusion

- Mixed ages: comfortable text sizes, high contrast in a dark room, no tiny tap targets.
- Low-light use: avoid large bright surfaces that blind people in a dark room.
