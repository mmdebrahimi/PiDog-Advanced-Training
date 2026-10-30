# PiDog Lab — Claude Instructions

## CRITICAL: Session Persistence
Sessions are lost on every Pi restart. The Pi restarts frequently.

**On session START:** Read `STATE_OF_PLAY.md` FIRST (consolidated current state — hardware truths, known-good calibration, open faults, next steps), then `SESSION_LOG.md` for chronology. Keep STATE_OF_PLAY.md updated whenever a fact in it changes.

**DURING session:** After every significant change:
1. Update `SESSION_LOG.md` with what was just done
2. Run `sync` to flush to SD card
3. Commit code (`git add <files> && git commit`)

**Auto-save cron** runs every 15 min and commits uncommitted changes.

**Memory files** (`~/.claude/projects/-home-pidog/memory/`) bridge sessions — update them for cross-project context that outlives this repo.

## Workspace
- Project root: `~/pidog_lab/`
- Venv: `source ~/pidog_lab/.venv/bin/activate`
- Python 3.13.5

## Running Scripts
All scripts must be run with the venv activated:
```bash
source ~/pidog_lab/.venv/bin/activate && python3 <script>.py
```

## Servo Control Rules
- Use `legs_move()` / `head_move_raw()` / `tail_move()` — NOT direct `Robot.servo_move()` or `Servo.angle()`
- Exception: `Servo.angle()` is safe for one-off zeroing when no Pidog instance exists
- Do NOT use `do_action()` — explicit angle control only
- Always `try/finally` with `my_dog.close()` to clean up subprocess
- Wait 1.5s after `Pidog()` init before servo commands
- Angle format: list of lists, e.g. `[[a0, a1, ..., a7]]` for legs

## Key File Paths
- SunFounder pidog library: `~/pidog_lab/pidog/pidog/pidog.py`
- SunFounder robot-hat library: `~/pidog_lab/robot-hat/robot_hat/`
- MuJoCo model: `~/pidog_lab/pidog.xml` (repo ROOT — `sim/` copy is LEGACY, see its banner)
- RL environment: `~/pidog_lab/pidog_env.py` (29-dim residual-on-trot; `sim/pidog_env.py` and `rl_training_package/` are LEGACY)
- Training script: `~/pidog_lab/train.py`
- MVP gates: `~/pidog_lab/eval_mvp.py` (SB3 .zip), `~/pidog_lab/eval_npz.py` (extracted deploy/*.npz — the artifact the robot runs)
- Deploy: `~/pidog_lab/deploy/deploy_pidog.py` (+ staged `policy_*.npz`, `power_audit.py`, runbooks)
- Servo map: `~/pidog_lab/joint_mapping.csv` (AUTHORITATIVE, user-verified wiggle test 2026-10; deploy loads it fail-closed)
- State logger: `~/pidog_lab/state_logger.py`
- Plans: `~/pidog_lab/plans/`
- Config (calibration): `~/.config/pidog/pidog.conf`
- STEP 3D model: `~/pidog_lab/sim/pidog-总体装配-2024-12-5.STEP`

## Important
- Robot HAT switch must be on GREEN LED (not red) for MCU/servos to work
- Camera being added by user for testing; `vilib` installed
- Install PyTorch CPU-only on Pi: `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- Full RL training should be done on desktop (~40 FPS on Pi vs ~400+ on laptop)
- Use `TMPDIR=/home/pidog/tmp` for pip installs — `/tmp` is RAM-based (1.9GB) and overflows with large packages

## Voice Companion
- **Full companion (with dog):** `python3 -m buddy.companion`
- **With video overlay:** `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video`
- **Face tracker standalone:** `QT_QPA_PLATFORM=xcb python3 -m buddy.face_follower [--log] [--detector auto|tflite|haar]`
- **Face enrollment:** `QT_QPA_PLATFORM=xcb python3 -m buddy.face_id --enroll "Name"`
- **List known faces:** `python3 -m buddy.face_id --list`
- Audio: sounddevice through PulseAudio (auto-detected pulse device) → HDMI output
- Set HDMI as default: `pactl set-default-sink alsa_output.platform-fef00700.hdmi.hdmi-stereo`
- HAT speaker anti-buzz: `~/.config/systemd/user/hat-speaker-mute.service` mutes the soc_sound sink at every boot (linger enabled); companion unmutes only while speaking
- Config files: `~/.config/pidog/names.json`, `openai_key`, `pidog-longterm-memory.md`, `known_faces.json`, `social_graph.json`, `personality.json`
- Safe mode ON by default (no walking — desk safe). Use `--no-safe` for floor testing.
- Always clear cache after edits: `find ~/pidog_lab/buddy -name "__pycache__" -exec rm -rf {} +`
- Dog name: Nounou. Wake word: "hi nounou". Sleep word: "goodnight".
- Voice commands: "who can you see?", "remember my face, I'm Alice"

## Person Tracking
- Detection: TFLite SSD MobileNet (~10 FPS) + Haar cascade on person ROI (every 3rd frame)
- Tracking: SORT (Kalman + Hungarian), persistent IDs, face ID via SFace embeddings
- Servo: detection thread (~10 FPS) + servo thread (30 Hz) for smooth head tracking
- Camera: OV5647 CSI, outputs BGR despite RGB888 config. Yaw ≤±55° for cable safety.
- Camera graceful degradation: if CSI cable is loose, companion runs without tracking (voice + actions still work)
- Models: `buddy/models/` — SFace + YuNet auto-download from OpenCV Zoo if missing

## Git Remote
- `origin` → `https://github.com/mmdebrahimi/PiDog-Advanced-Training.git`
- RL training updates pushed from laptop

## Behavior Engine
- `buddy/behavior_engine.py` — priority-based state machine, ticks every 2s
- Behaviors (highest priority wins): SLEEP > GREET > TRACK > SEARCH > REST
- Engine sets FaceFollower mode via `tracker.set_behavior_mode('track'|'idle'|'off')`
- LED ownership: engine owns ambient LEDs, voice callbacks own transient (speaking/thinking)
- `engine.restore_leds()` — called by `on_speaking_end` to return to behavior LEDs
- Sleep/wake lifecycle owned by engine: `engine.go_to_sleep()`, `engine.wake_up(source)`
- Touch wake routes through `DogBehavior._poll_sensors` callback, not engine polling
- Voice updates wrapped in `_update_voice()` to catch network failures

## Current Work
- RL Training: walking works in sim — 4 staged policies pass the MVP gate (`python eval_npz.py --report`); `policy_800k.npz` / `policy_trot29.npz` FAIL the gate (pre-residual) — NEVER deploy them
- Hardware deploy: GATED. Sequence: (1) P3 swap test + back-left shin servo replacement (shin servo DEAD, channel P0 good — swap fixes the leg); (2) hw_checkup brownout step test = the deploy gate (trot policies command 8 simultaneous servos, known brownout regime; crawl reference = 4); (3) tethered `deploy_pidog.py --stand` to confirm mapping/sign chain; then `policy_dr_robust.npz` first with `--slew-cap 2 --stagger-ms 5`
- Deploy safety: servo map comes ONLY from `joint_mapping.csv` (fail-closed); writes go through the I2C-locked `legs_move` buffer; battery prompt blocks policy runs on USB power
- Voice Companion: working via Realtime API with person tracking + room awareness
- Behavior Engine: working (GREET/TRACK/SEARCH/REST/SLEEP, LED ownership, sleep/wake)
- Person Tracking: working (YuNet-first + TFLite fallback + MOSSE inter-frame + SORT + face ID)
- Memory v2: semantic (per-person facts + dedup + topics) + episodic (session summaries) + combined single-call extraction
- Smart Arrivals: identity-aware GREET (Alice=excited bark, family=warm, known=friendly, stranger=shy→curious)
- Door watching: REST behavior points head at saved door direction when alone
- Personality: v3 (valence-arousal emotion, needs, mood-driven actions, time-of-day awareness, enriched character)
- Wake from sleep: head pat + voice wake both working
- Sound direction: disabled (fires on ambient noise, conflicts with servo thread)
- All 30 ActionFlow actions available to LLM
- Shutdown: Ctrl+C works (first=graceful, second=force quit)
- Volume: ramped 50→80% at startup (child-safe cap), never exceeds 80%
- Safety: Asimov's Three Laws in LLM system prompt (kid-friendly)
- Plans index: `~/pidog_lab/wiki/plans-index.md`
- Personality v3: needs system (attention/stimulation/rest), emotion decay (exponential VA model), touch→mood, departure→sadness, stranger→shy, idle spontaneous behaviors, jealousy mechanic, enhanced sleep/wake rituals
- Spatial Memory: absolute angular tracking, distance estimation, occlusion persistence (10s Kalman coast), rich scene descriptions for LLM
