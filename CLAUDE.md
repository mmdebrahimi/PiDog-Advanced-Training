# PiDog Lab — Claude Instructions

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
- MuJoCo model: `~/pidog_lab/sim/pidog.xml`
- RL environment: `~/pidog_lab/sim/pidog_env.py`
- Training script: `~/pidog_lab/sim/train.py`
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
- Config files: `~/.config/pidog/names.json`, `openai_key`, `pidog-longterm-memory.md`, `known_faces.json`
- Safe mode ON by default (no walking — desk safe). Use `--no-safe` for floor testing.
- Always clear cache after edits: `find ~/pidog_lab/buddy -name "__pycache__" -exec rm -rf {} +`
- Dog name: Nounou. Wake word: "hi nounou". Sleep word: "goodnight".
- Voice commands: "who can you see?", "remember my face, I'm Alice"

## Person Tracking
- Detection: TFLite SSD MobileNet (~10 FPS) + Haar cascade on person ROI (every 3rd frame)
- Tracking: SORT (Kalman + Hungarian), persistent IDs, face ID via SFace embeddings
- Servo: detection thread (~10 FPS) + servo thread (30 Hz) for smooth head tracking
- Camera: OV5647 CSI, outputs BGR despite RGB888 config. Yaw ≤±55° for cable safety.
- Models: `buddy/models/` — SFace + YuNet auto-download from OpenCV Zoo if missing

## Git Remote
- `origin` → `https://github.com/mmdebrahimi/PiDog-Advanced-Training.git`
- RL training updates pushed from laptop

## Current Work
- RL Training: in progress on laptop (reward tuning, CUDA training)
- Voice Companion: working via Realtime API with person tracking + room awareness
- Person Tracking: working (TFLite + SORT + face ID + room awareness)
- Wake from sleep: needs fixing (WebSocket may stop transcribing after go_to_sleep)
- Plans index: `~/pidog_lab/wiki/plans-index.md`
