# Session Log

> Auto-updated during Claude Code sessions. Read this first on every new session.

## Latest session: 2026-06-12

### What we did
1. Built and integrated **Behavior Engine** (`buddy/behavior_engine.py`) — priority state machine with GREET/TRACK/SEARCH/REST/SLEEP
2. Executed **Head Tracking Smoothing** plan — tuned coast (15 frames), sweep (8s), face lost (4s), lock-on alpha (0.3)
3. Executed **Vision Pipeline Upgrade** — switched Haar→YuNet, added MOSSE inter-frame tracker, added dead zone
4. Added **shutdown voice command** — say "shutdown"/"power off" for full graceful stop
5. Added **camera graceful degradation** — companion runs without tracking if CSI fails
6. Expanded safe_actions — added `waiting`, `twist body`, `doze off`, `feet shake`
7. User manually added: personality traits (butterfly dreams, fav colour, bone cookies), time-of-day context, mood-driven actions, stranger greeting flow, door-watching REST

### Camera status
CSI cable keeps disconnecting. User plans to reposition Pi board so CSI port faces head. Camera passed `rpicam-hello` test at end of session.

### What's next
1. **TOMORROW MORNING: First Alice test** — run `python3 -u -m buddy.companion` and let Alice talk to Nounou. Test checklist:
   - Walk into room → GREET with her name?
   - Voice conversation working?
   - Smooth head tracking (no jitter)?
   - "Goodnight" → sleep, head pat → wake
   - "Shutdown" → full stop
2. Add BT speaker (so audio comes from the dog)
3. Reposition Pi board if CSI cable still disconnects

### Git status
All code committed via auto-save cron. Plans archived to `executed_plans/`.

## 2026-08-11 — Permanent boot-time speaker mute (anti-buzz)

- Buzz on every restart = HAT I2S amp sink (card 3, googlevoicehat/MAX98357A) coming up unmuted before companion.py runs.
- Fix: user systemd service `~/.config/systemd/user/hat-speaker-mute.service` — waits for PipeWire, mutes any `alsa_output.*soc_sound*` sink (30s retry, pattern-matched so card renames survive). Enabled + verified (exit 0, sink muted).
- `loginctl enable-linger pidog` so the user session (and the mute) starts at boot, not at desktop login.
- Companion speech unmute/mute logic unchanged — it still unmutes only while speaking.

## 2026-08-11 — Back-left leg root cause FOUND: direction inversion

- User hypothesis confirmed by flip test: back-left leg (idx4 hip pin0, idx5 knee pin1) runs DIRECTION-INVERTED vs stock convention. Zero pose can't reveal it (90-degree L looks identical mirrored) — that's why zero always looked perfect while every pose was wrong.
- Permanent fix: `leg_directions = [1,1,1,1,-1,-1,1,1]` passed to Robot() in pidog.py (source + site-packages deployed).
- IMPORTANT: direction flip also reverses OFFSET effect on that leg — offset tweaks on idx4/5 act backwards vs other legs.
- Sit verified good by user with runtime offsets: knee idx5 -30, hip idx4 0, tail -45 (tail = swapped-in servo, horn mounted ~45 deg off). NOT yet persisted to pidog.conf.
- Open: close()/stop_and_lie slams lie pose at speed 85 — end-of-run pose shows thigh ~90 deg to ground on back-left; slow-vs-fast A/B run done, user observation pending.
- Speaker buzz truly fixed: GPIO12 (HAT v5 amp enable) held low at boot by hat-speaker-mute.service; companion toggles it around speech.

## 2026-08-20 — Buzz recurrence after HAT power-cycle: resolved

- HAT power-cycle brought the buzz back DESPITE GPIO12 low + sink muted. Amp-pin toggles had no audible effect this time; buzz correlated with Pi activity (static blip on message send).
- Cleared after stacking: MCU reset + GPIO12 low + GPIO20 low (robot_hat detects HAT as v4 → spk_en=20) + sink muted. Exact lever ambiguous — boot service now applies ALL pins (12 + 20) + mute.
- companion.py signal_handler now calls _mute_speaker() first on any shutdown, so a crash mid-speech can't leave the sink unmuted.
- WATCH: if buzz returns after next HAT power-cycle, re-run the pin-toggle discrimination; wiring splice (bridge-tied amp output vs ground) still a suspect if load-correlated static reappears.
