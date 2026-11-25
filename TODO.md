# TODO — turning this box into the karaoke machine

This PC (Arch, Radeon RX 6800 / ROCm, Hyprland) **is** the karaoke machine. Nothing moves
to other hardware; the goal is to make it start, run and be checked on like an appliance.

## 1. Admin / setup panel (next up)

**Goal:** one local menu to start everything and see what is running, instead of
remembering `./start-karaoke.sh` flags and reading tmux panes.

### Decided (2026-11-24)
- **Form:** a small web panel, a separate program from the karaoke app, so it keeps
  working when the app is stopped or has crashed. Opened here as an app window
  (app-launcher entry).
- **Runner:** each piece becomes a **systemd user service** (ASR/GPU server, karaoke app,
  headless TV stream, Cloudflare tunnel). The panel drives `systemctl --user` and reads
  `journalctl --user`, so crash detection, auto-restart and logs come for free. This
  replaces the tmux session in `start-karaoke.sh`.
- **Startup:** nothing automatic. No service is enabled at login, the panel included; you
  open it from the launcher and press Start.
- **Access:** this PC and the **tailnet** only (this box is `atenea`, 100.96.219.97).
  Never on the plain LAN, never through the Cloudflare tunnel.
- **Status view:**
  - Service health: each piece up/down, uptime, last error, log tail.
  - Join info: phone URL, TV URL, public tunnel URLs, with QR codes.
  - Live activity: now playing, queue length, background jobs (vocal splits,
    color-wipe generation).
  - Machine health (GPU/VRAM, disk) was not picked; leave it out for now.
- **Controls:**
  - Start/stop/restart by mode: on this monitor, streamed to the TV (cage), or
    published through the tunnel.
  - Settings: admin password, Whisper model, TV quality/scale, song folder, public
    hostnames. Saved to a config file that the services read, replacing launcher flags
    and the hardcoded hostnames.
  - Library maintenance: pre-split vocals, generate missing color-wipes, clean up orphans
    and partial downloads (the leftovers below are the first test case).
  - Updates: yt-dlp (show the version and the last auto-update), pull from fork/upstream,
    show what changed.

### Still open
- **How to restrict access to localhost + tailnet.** One option is to bind 127.0.0.1 and the
  Tailscale IP. That fails if tailscaled comes up after the panel. The other is to bind
  all interfaces and allow only 127.0.0.1 / ::1 / 100.64.0.0/10 / fd7a:115c:a1e0::/48.
  Also open: whether to require a password on the tailnet too, or trust Tailscale
  identity (`tailscale whois` on the peer, allowing only your own user).
- Port, and what the "app window" is (e.g. a browser `--app=` window).
- How live activity is read: from the app's existing endpoints/websocket, or a small
  status endpoint added to `app.py` and `asr_server.py` (the jobs queue lives there).
- Whether `start-karaoke.sh` stays as a CLI shortcut over the same services or is removed.

## 2. Pending work

### Features
- **Scoring** (`scoring` branch, commit `f40ab62`, local only, not pushed). It scores the
  singer against the isolated vocal stem (pyin pitch class, ±3s alignment search). Merges
  cleanly into master. Still to decide: wire it into the end-of-song flow, or keep it as an
  experiment.
- **Lyrics panel** (merged). Only the `.ass` reader has run on real files (all 90 songs).
  The `.srt` / `.vtt` / `.lrc` / `.txt` readers and the embedded-subtitle ffmpeg path are
  untested, and the panel hasn't been opened in a real phone browser yet.
- **Headless video in cage** (`start-karaoke.sh -t`). The splash screen and VLC start
  are verified; full song video playback inside cage was never confirmed with a real song.

### Appliance hardening
- **`key.pem` / `cert.pem` come from upstream.** Every clone of the project shares the same
  publicly available private key. Generate a per-machine cert (or get a real one via the
  Cloudflare hostname) and stop tracking the pair.
- **Hostnames are hardcoded** in `start-karaoke.sh` (`karaoke.` / `tv.timbear.gratis`).
  Move them to a config file the panel can edit.
- **yt-dlp drift.** The app upgrades `yt-dlp[default]` once a day at start-up, so the venv
  runs ahead of the `requirements.txt` pin. That is right for an appliance (YouTube breaks
  old versions), but the panel should show the yt-dlp version and when it last updated.
- **`deno` is a system dependency** for YouTube downloads (the JS challenge solver).
  Any setup or health check should verify it is installed.
- **`run.sh` is upstream's launcher and is broken here** (it uses system python3 and
  `pacmd`). Delete it or leave it alone; the panel replaces it.

### Library hygiene (`~/pikaraoke-songs`, nothing deleted yet)
- 7 orphan `.ass` files whose media is gone (the songs were re-downloaded under another
  ID or deleted): unravel (TK MV), Paparazzi ×2, Be a flower (`ee3ca1dc…`), Sweet Child
  O' Mine, Roly Poly, Stay with Me [MV].
- Leftover partial downloads: one `.part` in the library root and 67 MB in `tmp/`
  (Fullmetal Alchemist OP attempts).
- A good candidate for a "clean up library" action in the panel.
