# STATE OF PLAY — Nounou (PiDog companion for Alice)

> Single source of truth for cross-session continuity. Read this FIRST in every new
> session (before SESSION_LOG.md details). Update it whenever a fact here changes.
> Last full revision: 2026-08-29.

## Mission
Companion robot dog for Alice (7). Software companion (voice + vision + behavior) is
~90% done and was Alice-ready; the blocker since early August is REAR-LEG POSE QUALITY
(sit/stand) — now traced to hardware, see Faults.

## Hardware truths (hard-won — do not re-derive)
- **Back-left leg (idx4 hip=pin0, idx5 knee=pin1) is DIRECTION-INVERTED** vs stock
  convention. Fixed permanently in `pidog/pidog/pidog.py`: `leg_directions =
  [1,1,1,1,-1,-1,1,1]` passed to `Robot()`. Deployed to venv site-packages.
  - Offsets on that leg act REVERSED (direction multiplies offset).
  - A mirrored 90° L looks IDENTICAL at zero → **zero pose can never reveal direction
    faults**. Diagnose with excursion+return, never zero.
- **Servo history:** original back-left KNEE servo died (hot/hunting) → swapped with
  tail servo. The ex-tail servo now in the BACK-LEFT HIP **is also bad** (see Faults).
  Old dead knee servo lives in the TAIL (45° off, harmless, no vibration).
- **Libraries are NOT pip-editable.** Source lives in `~/pidog_lab/pidog/` and
  `~/pidog_lab/robot-hat/`; every patch must be `cp`'d into
  `.venv/lib/python3.13/site-packages/...` AND import-verified, else it silently
  doesn't run.
- **robot_hat detects this HAT as v4** (UUID unmatched) → its speaker-enable pin is
  GPIO 20; v5 mapping would be GPIO 12. Every `Pidog()` init runs
  `pinctrl set 20 op dh`.
- **HAT power switch shares power with the Pi** — toggling it reboots everything.
- **Pi has no RTC** — early-boot timestamps are stale until NTP jumps (confused a
  systemd-service investigation once).
- **Power:** servos need the battery (healthy = 8.4V) or a real supply
  (laptop charger = 7.87V works). Monitor USB-C browns out on servo load → instant
  reboot. Check `get_battery_voltage()` + `vcgencmd get_throttled` before servo work.

## Known-good sit recipe (VERIFIED by user 2026-08-11)
Archived at `captures/known_good_sit.json`. Diff live state against it before
re-deriving anything:
- directions `[1,1,1,1,-1,-1,1,1]` (in pidog.py)
- `pidog.conf`: legs offsets `[0,0,0,0,0,-30,0,0]`, tail `[-45]` (conf load path
  accepts beyond the ±20 `set_offset` clamp)
- sit angles `[30,60,-30,-60,80,-45,-80,45]`, zero all-0
- `stop_and_lie` speed patched 85→30 (gentle shutdown slam)

## Faults OPEN (2026-08-29)
1. **Back-left HIP servo (pin 0) slips under load** — convicted by raw repeatability
   test (bare `Servo('P0')`, 3× 0/+45/0/-45/0, webcam pixel-diff): commanded-zero
   drifted 6.9→14.4→15.6% frame-change (a real 45° swing = 6.8%), monotonic rearward
   ratchet. Below ALL software. This is why the good sit "regressed".
   Next: horn-screw check/tighten (hold P0 at zero first!), else replace servo.
2. **Replacements needed: 2 servos** (back-left hip + tail slot). Purchase = user
   decision, not yet placed.
3. **Head yaw servo hunts** (fast left-right shake on body movement) — unresolved;
   check neck horn screw, else swap-test.
4. **CSI camera undetected** since board repositioning — companion degrades to
   voice-only gracefully. eMeet USB webcam on /dev/video0 (index shifts across
   reboots; needs MJPG fourcc for 1080p) used for debugging.

## Speaker / buzz (SOLVED — layered)
- Wired HAT speaker (user-soldered onto old speaker's cut wires, bridge-tied amp).
- Boot: `~/.config/systemd/user/hat-speaker-mute.service` (linger enabled) drives
  GPIO 12 AND 20 low + mutes `alsa_output.platform-soc_sound.stereo-fallback`.
- companion.py: unmutes amp+sink only while speaking; `signal_handler` re-mutes on
  ANY exit (a crash mid-speech once left it unmuted overnight).
- FINAL VERDICT (2026-08-29): buzz = the HAT amp's intrinsic NOISE FLOOR through the
  user's bigger/more-sensitive replacement speaker. Confirmed cone-sourced while amp
  pins low + sink muted + PWM stopped + on battery — the amp stage is effectively
  always live; no software sits between its noise and the cone. GPIO12/20 "fixes"
  were coincidental. Do NOT re-attempt software fixes. Remedies: unplug speaker plug
  at HAT socket (bench), series resistor 10-22R in one lead (attenuate), or BT
  speaker (recommended — companion already prefers BT sink; original plan anyway).

## Debug method that WORKS here (learned the hard way)
- ONE variable per run; user judges pose (their eye > camera for pose quality; my
  image readings were overruled repeatedly).
- Camera IS decisive for: repeatability pixel-diff, gross asymmetry, wiring photos.
- Raw `Servo('P<n>')` test separates software from hardware in one run.
- Sweep protocol (4-5 values held 4s each, user names best step) converges fast.
- User's "software issue" instincts have been right before (direction inversion) —
  but the raw test now proves the current fault is hardware; evidence beats belief
  in BOTH directions.

## Software state (all deployed + in git)
- Behavior engine, YuNet+MOSSE+SORT tracking, Memory v2, personality v3, smart
  arrivals, shutdown voice cmd, camera degradation, volume ramp 50→80% cap.
- Companion entry: `python3 -m buddy.companion` (venv). Wake "hi nounou",
  sleep "goodnight", full stop "shutdown".
- RL training track: stalled, lives on laptop (Zscaler blocks Pi↔laptop transfer;
  use email).

## Next steps (priority order)
1. Fix back-left hip: horn tighten (P0 held at zero) or servo swap → re-run raw
   repeatability → re-verify sit vs `known_good_sit.json`.
2. Order 2 replacement servos (user purchase).
3. Stand tuning (was mid-sweep when the hip fault interfered) → IMU
   `auto_level2.py` for quantitative finish (dog flat on table, feet loaded).
4. Head-yaw hunting, CSI cable re-seat.
5. Alice first-interaction test (the actual goal — checklist in SESSION_LOG
   2026-06-12 entry).

## Key files
- This file + `SESSION_LOG.md` (chronology) + `project_state/nounou-alices-robot-dog-2026-06-10.md` (ledger)
- `captures/known_good_sit.json` — calibration reference
- `~/.config/pidog/pidog.conf` — live offsets (backup: pidog.conf.bak)
- `pidog/pidog/pidog.py` + `robot-hat/robot_hat/robot.py` — patched sources (deploy = cp to site-packages)
- Auto-memory: `~/.claude/projects/-home-pidog/memory/` (cross-project facts)
