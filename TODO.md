# TODO — turning this box into the karaoke machine

This PC (Arch, Radeon RX 6800 / ROCm, Hyprland) **is** the karaoke machine. Nothing moves
to other hardware; the goal is to make it start, run and be checked on like an appliance.

## 1. Admin / setup panel (built on the `panel` branch)

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
  open it from the launcher ("Karaoke Panel" = `scripts/ohk-panel`) and press Start.
- **Window:** a `chromium --app` window (own profile, window class `ohk-panel`), not a
  native app. Your phone over the tailnet needs the web UI anyway, so a native app would
  be a second UI to maintain.
- **Port:** 12345.
- **Access:** this PC and the **tailnet** only (this box is `atenea`, 100.96.219.97).
  Never on the plain LAN, never through the Cloudflare tunnel. Tailscale is always on, so
  the panel binds only loopback + the Tailscale addresses, and trusts tailnet peers logged
  in as this machine's own Tailscale user (`tailscale whois`). No password.
- **Live activity:** new status endpoints, `app.py /ohk_status` (guest-visible data only)
  and `asr_server.py /status` (GPU work: current split/build, backlog).
- **`start-karaoke.sh`** stays as a CLI shortcut; the panel supersedes it. Each refuses to
  start while the other is running.
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

### Tested (2026-11-24)
- Access gate: loopback and own-user tailnet (IPv4, IPv6, MagicDNS) get in; the LAN can't
  connect; a foreign Host header (DNS rebinding), tunnel/proxy headers, form POSTs and
  foreign Origins are refused.
- TV mode end to end from the panel: GPU server ready in ~16s, app + stream healthy, join
  QR codes, a real song playing with video in cage (first confirmation of that), "Now"
  card live, a job run as a transient unit with its log, and Stop leaving no processes,
  ports or audio sink behind. The admin password never appears in any log.
- Public mode refuses to start without an admin password. Cleanup tested on a scratch
  library: moves only orphans/old partials, refuses real songs and path tricks.

### Not tested yet
- **Monitor mode** (it takes over this screen).
- **Public mode for real** (needs an admin password set, then exercises the tunnel).
- Opening the actual app window from the launcher, and the panel from a phone on the
  tailnet. Also refusing a tailnet device logged in as a *different* Tailscale user (no
  such device to try).
- The leftover cleanup on the real library: left for you to press.

### Ideas, later
- Merge `panel` into master once monitor and public modes are tried.
- Machine health card (GPU/VRAM, disk) if it turns out to be missed.

## 2. Pending work

### Features
- **Scoring** (`scoring` branch, commit `f40ab62`, pushed to the fork). It scores the
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
- **Hostnames:** now editable in the panel's settings (`~/.config/ohk/config.json`);
  `start-karaoke.sh` still has them hardcoded.
- **yt-dlp drift.** The app upgrades `yt-dlp[default]` once a day at start-up, so the venv
  runs ahead of the `requirements.txt` pin. That is right for an appliance (YouTube breaks
  old versions), but the panel should show the yt-dlp version and when it last updated.
- **`deno` is a system dependency** for YouTube downloads (the JS challenge solver).
  Any setup or health check should verify it is installed.
- **`run.sh` is upstream's launcher and is broken here** (it uses system python3 and
  `pacmd`). Delete it or leave it alone; the panel replaces it.

- **A song whose name starts with "." is invisible to the app** (`...Baby One More Time`):
  `get_available_songs` skips dotfiles. The panel's Library card lists it.

### Library hygiene (`~/pikaraoke-songs`, nothing deleted yet)
- 7 orphan `.ass` files whose media is gone (the songs were re-downloaded under another
  ID or deleted): unravel (TK MV), Paparazzi ×2, Be a flower (`ee3ca1dc…`), Sweet Child
  O' Mine, Roly Poly, Stay with Me [MV].
- Leftover partial downloads: one `.part` in the library root and 67 MB in `tmp/`
  (Fullmetal Alchemist OP attempts).
- The panel's Library card offers exactly these (moves them to `~/.local/share/ohk/trash/`).
- 4 songs exist twice, as `.mp4` + `.webm` (Wannabe, This Is Me, Lamento Boliviano,
  These Boots…): listed, not touched.
