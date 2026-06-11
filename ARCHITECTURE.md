# Architecture

## Control Stack

```
Pidog class (pidog/pidog.py)
  - legs_move() / head_move() / tail_move()  [thread-safe buffer API]
  - Action threads (1 per body part) consume buffers
      |
Robot class (robot_hat/robot.py)
  - servo_move()  [smooth interpolation, 10ms steps]
  - servo_write_raw()  [immediate write]
      |
Servo class (robot_hat/servo.py)
  - angle()  [maps degrees to pulse width, clamps +/-90]
      |
PWM class (robot_hat/pwm.py)
  - pulse_width_time()  [500-2500 us]
      |
I2C class (robot_hat/i2c.py)
  - Writes to onboard MCU registers
      |
Hardware MCU
  - Generates 50Hz PWM on servo pins
```

## Threading Model

Pidog spawns 5-6 threads + 1 subprocess on init:

| Thread | Daemon | Purpose |
|--------|--------|---------|
| legs_thread | Yes | Consumes legs_action_buffer, calls legs.servo_move() |
| head_thread | Yes | Consumes head_action_buffer, calls head.servo_move() |
| tail_thread | Yes | Consumes tail_action_buffer, calls tail.servo_move() |
| rgb_strip_thread | Yes | Updates RGB LED animations |
| imu_thread | Yes | Reads SH3001 IMU, calibrates on startup (~1s) |
| sensory_process | No (Process) | Reads ultrasonic sensor via separate subprocess |

**Critical:** `Robot.servo_move()` has no locking. I2C bus locks are commented out in the library. Only one thread should call `servo_move()` per Robot instance — the action thread pattern enforces this.

## Sensor Addresses (I2C bus 1)

| Device | Address | Purpose |
|--------|---------|---------|
| Servo MCU | 0x14-0x17 | PWM generation for 12 servos |
| SH3001 IMU | 0x36 | Accelerometer + gyroscope |
| SLED1735 | 0x74 | RGB LED driver (11 LEDs) |

## Data Flow: Servo Command

```
User: legs_move([[angles]], immediately=True, speed=30)
  -> acquires legs_thread_lock
  -> clears buffer (if immediately)
  -> appends angle frame to legs_action_buffer
  -> releases lock

legs_thread (background):
  -> acquires lock, copies buffer[0]
  -> releases lock
  -> calls legs.servo_move(angles, speed)
    -> calculates timing from speed
    -> interpolates in 10ms steps
    -> each step: servo_write_all() -> servo.angle() -> PWM -> I2C
  -> acquires lock, pops buffer[0]
```

## Configuration

- Servo calibration offsets: `~/.config/pidog/pidog.conf`
- Format: plaintext key-value, e.g. `legs_servo_offset_list = [0, 0, 0, 0, 0, 0, 0, 0]`
- Created automatically on first run with zero offsets
- Not atomic — can corrupt on power loss during write

## Simulation Stack (MuJoCo)

```
train.py (PPO training via stable-baselines3)
    |
pidog_env.py (Gymnasium environment)
    |
pidog.xml (MJCF model: 8 position actuators, freejoint torso)
    |
MuJoCo 3.6.0 (physics engine, CPU-only)
```

**Model geometry** (from `pidog.py` constants):
- Body: 117×98mm box, ~300g
- Upper leg: 42mm capsule, ~20g
- Lower leg: 76mm capsule, ~15g
- Hip positions: ±49mm lateral, ±58.5mm longitudinal
- Right-side joint axes flipped (`0 -1 0`) for mirrored sign convention

**Actuators:** `<position>` type with `kp=200`, `ctrlrange=[-60, 60]` degrees. Models hobby servo PID behavior.

**Development split:**
- Pi 4: real robot control, data collection, policy inference
- Desktop: MuJoCo visualization, RL training (40 FPS on Pi vs ~400+ on desktop)

## Voice Companion + Person Tracking Stack (buddy/)

**Architecture:**
```
companion.py (init + main loop: pumps video, calls engine.tick())
    |
    ├── behavior_engine.py (priority state machine, 2s tick)
    │     ├── Reads: RoomState, PersonalityState, FaceFollower.is_tracking()
    │     ├── Sets: FaceFollower behavior mode (track/idle/off)
    │     ├── Controls: LED patterns, spontaneous actions, context injection
    │     ├── Owns: sleep/wake lifecycle, arrival/departure hooks, jealousy
    │     └── Behaviors: SLEEP > GREET > TRACK > SEARCH > REST
    │
    ├── realtime_voice.py → WebSocket to gpt-4o-realtime-preview
    │     ├── Mic (sounddevice via PulseAudio, 24kHz) → server-side VAD → model
    │     ├── Audio response → HDMI output
    │     ├── Tools: perform_action, go_to_sleep, who_is_here, remember_face
    │     └── update_instructions() for live room context injection
    │
    ├── face_follower.py (2 threads)
    │     ├── Detection thread (~10 FPS): capture → TFLite person detect
    │     │     → Haar face detect (every 3rd frame) → SORT tracker
    │     │     → face ID submission → write servo target
    │     ├── Servo thread (30 Hz): read target → proportional + EMA → head_move()
    │     └── set_behavior_mode(): engine controls track/idle/off
    │
    ├── servo_controller.py → proportional + adaptive EMA (no Kalman — SORT handles that)
    ├── detectors.py → PersonDetector (TFLite SSD), FaceDetector (Haar), HeadEstimator
    ├── tracker.py → SORT (Kalman per track + Hungarian assignment via scipy)
    ├── face_id.py → FaceEmbedder (SFace 128-dim) + FaceDatabase (JSON) + async worker
    ├── room_awareness.py → who's here, where last seen, LLM context summaries
    ├── dog_behavior.py → Pidog + ActionFlow (30 physical behaviors) + LED control
    └── memory.py → ~/.config/pidog/pidog-longterm-memory.md
```

**Person tracking pipeline:**
```
Camera (OV5647 CSI, 640×480)
    → PersonDetector (TFLite SSD MobileNet, ~10 FPS)
    → FaceDetector (Haar cascade on person ROI, every 3rd frame)
    → HeadEstimator (top 12% of person bbox when no face visible)
    → SORT Tracker (persistent IDs, Kalman prediction, Hungarian matching)
    → FaceIDWorker (async SFace embedding → JSON known_faces.db match)
    → RoomState (who_is_here, get_summary → LLM context)
    → ServoController (proportional + EMA → head_move at 30 Hz)
```

**Audio devices:**
- Input: USB webcam mic via PulseAudio (auto-detected pulse device)
- Output: HDMI via PulseAudio (auto-detected, `pactl set-default-sink` for HDMI)
- I2S Robot HAT speaker: not producing audio on this HAT v4 revision

**Camera:**
- OV5647 CSI camera via picamera2 at 640×480
- Outputs BGR despite `format: "RGB888"` — no cvtColor needed for imshow
- Yaw limited to ±55° to protect CSI ribbon cable
- Video display: `QT_QPA_PLATFORM=xcb` required for OpenCV QT5 backend

**Audio output selection:**
- BT speaker auto-detected at startup (scans for bluez/bluetooth PulseAudio sinks)
- Falls back to HDMI if no BT speaker paired

**Persistent state:**
- Names: `~/.config/pidog/names.json`
- Legacy memory: `~/.config/pidog/pidog-longterm-memory.md` (flat, v1 fallback)
- Semantic memory: `~/.config/pidog/semantic_memory.json` (per-person facts, milestones, topics)
- Episodic memory: `~/.config/pidog/episodic_memory.json` (rolling session summaries)
- Known faces: `~/.config/pidog/known_faces.json`
- API key: `~/.config/pidog/openai_key`
- Usage log: `~/.config/pidog/usage.json` (session durations for API cost awareness)
- Models: `buddy/models/` (SFace 37MB, YuNet 0.2MB — auto-downloaded from OpenCV Zoo)

## Known Library Issues

1. **I2C locks commented out** — concurrent I2C access from multiple threads is unprotected. Mitigated by action thread pattern (one thread per Robot instance).
2. **Silent angle clamping** — `Servo.angle()` clamps to +/-90 without warning.
3. **Silent I2C failure** — `_retry_wrapper` returns False after 5 retries, caller ignores return value. Servo state can diverge from physical position.
4. **MCU reset on init** — All servos lose PWM state for ~1.4s during `Pidog()` construction. Robot must be lying down or lifted.
