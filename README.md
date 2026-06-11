# PiDog Lab

Workspace for learning robotics ground-up with a SunFounder PiDog robot on Raspberry Pi. The project follows a phased approach from raw servo control through MuJoCo simulation and reinforcement learning.

## Hardware

- Raspberry Pi (aarch64, Linux 6.12.47+rpt-rpi-v8)
- SunFounder PiDog robot (12 servos, IMU, ultrasonic, touch, sound direction, RGB LEDs)
- Camera: OV5647 CSI camera (640×480) — mounted on head for person tracking
- USB webcam (eMeet C960) — used for mic input
- I2S Audio: Robot HAT speaker not producing audio on this revision; using HDMI output

## Setup

```bash
# Activate the virtual environment
source ~/pidog_lab/.venv/bin/activate

# Run any script
python3 <script>.py
```

### Installed Libraries

| Package | Version | Source |
|---------|---------|--------|
| robot-hat | 2.3.6 | `~/pidog_lab/robot-hat/` (cloned from SunFounder GitHub) |
| pidog | 1.3.11 | `~/pidog_lab/pidog/` (cloned from SunFounder GitHub) |
| vilib | 0.3.18 | `~/pidog_lab/vilib/` (camera library, picamera2 branch) |
| mujoco | 3.6.0 | Physics simulation engine |
| torch | 2.11.0+cpu | CPU-only PyTorch for RL |
| gymnasium | 1.2.3 | RL environment wrapper |
| stable-baselines3 | 2.8.0 | PPO implementation |
| openai | 2.30.0 | ChatGPT + Whisper + TTS + Realtime APIs |
| ai-edge-litert | 2.1.3 | TFLite runtime for person detection |
| filterpy | 1.4.5 | Kalman filters for SORT tracker |
| scipy | 1.17.1 | Hungarian assignment for SORT tracker |
| onnxruntime | 1.24.4 | Face recognition inference |

Python 3.13.5 with `--system-site-packages` venv for GPIO access.

### System Dependencies

espeak, libsdl2-dev, libsdl2-mixer-dev, sox, portaudio19-dev, pyaudio, i2c-tools, python3-smbus/smbus2, gpiozero, spidev, pyserial, pillow, pygame

### I2C/SPI

Enabled via `raspi-config`. SunFounder dtoverlays copied to `/boot/firmware/overlays/`. Reboot required to activate.

## Project Structure

```
~/pidog_lab/
  .venv/              # Python venv (--system-site-packages)
  robot-hat/          # SunFounder HAT library (cloned)
  pidog/              # SunFounder PiDog library (cloned)
  vilib/              # SunFounder camera library (cloned)
  sim/                # MuJoCo simulation (MJCF model, RL env, training)
    pidog.xml         # MuJoCo model (8 actuators, correct geometry)
    pidog_env.py      # Gymnasium RL environment
    train.py          # PPO training script
    sim_trot.py       # Scripted gait in sim
  logs/               # State logger output (CSV at 50Hz)
  plans/              # Implementation plans
  executed_plans/     # Completed plans
  hardware_check.py   # I2C device verification
  joint_test.py       # CLI joint testing tool
  joint_mapping.csv   # 12-joint reference table
  sensor_check.py     # Sensor verification
  state_logger.py     # 50Hz background state logger
  first_gait.py       # Manual diagonal trot gait
  buddy/              # Voice companion ("Nounou") + person tracking
    companion.py      # Full companion entry point (python3 -m buddy.companion [--video])
    behavior_engine.py # Priority-based behavior state machine (GREET/TRACK/SEARCH/REST/SLEEP)
    realtime_voice.py # OpenAI Realtime API WebSocket voice session
    config.py         # Names, prompts, thresholds
    dog_behavior.py   # Pidog + ActionFlow wrapper (safe mode, LEDs)
    face_follower.py  # Person tracking orchestrator (detection + servo threads)
    servo_controller.py # Proportional + EMA servo control
    detectors.py      # PersonDetector (TFLite), YuNetDetector (DNN), HeadEstimator
    tracker.py        # SORT tracker (Kalman + Hungarian assignment)
    face_id.py        # Face recognition (SFace embeddings + JSON database)
    room_awareness.py # Who's here, where last seen, absolute angular positions
    spatial_memory.py # Mental map: angular tracking, distance, velocity, scene descriptions
    social_graph.py   # People database (roles, relationships, interests)
    personality.py    # Personality v3: valence-arousal emotion, needs system, event hooks (persistent)
    semantic_memory.py # Per-person fact storage with dedup, milestones, topic counters
    episodic_memory.py # Rolling session summaries per person (last 10 sessions)
    memory_compiler.py # Compiles all memory sources into LLM context
    memory.py         # Memory extraction at shutdown (combined single API call)
    models/           # ONNX models (SFace, YuNet — gitignored, auto-downloaded)
    main.py           # Legacy 3-call pipeline entry point
  wiki/               # Plans index, decisions log
```

## Servo Layout

```
                 4,
               5, '6'
                 |
          3,2 --[ ]-- 7,8
                [ ]
          1,0 --[ ]-- 10,11
                 |
                '9'
                /
```

| Body Part | Servo Pins | Control API | Angle Format |
|-----------|-----------|-------------|--------------|
| Legs (8) | [2,3,7,8,0,1,10,11] | `legs_move()` | n*8 2D list |
| Head (3) | [4,6,5] yaw/roll/pitch | `head_move_raw()` | n*3 2D list |
| Tail (1) | [9] | `tail_move()` | n*1 2D list |

## Safety Rules

- Use `legs_move()` / `head_move_raw()` / `tail_move()` with `immediately=True` — NOT direct `Robot.servo_move()`
- Do NOT use `do_action()` — use explicit angle control
- Wait 1.5s after `Pidog()` construction before moving
- Always use `try/finally` with `my_dog.close()`
- Test one joint at a time, small increments, robot lifted
- Use speed=30 for experimental moves

## Phase Roadmap

| Phase | Name | Status |
|-------|------|--------|
| 0 | System Setup | Done |
| 1 | Dev Environment | Done |
| 2 | ~~API Discovery~~ | Done (collapsed) |
| 3 | Direct Joint Control | Done |
| 5 | Logging (50Hz) | Done |
| 6 | First Manual Gait | Done (basic) |
| 7 | ROS 2 Integration | Deferred |
| 8 | MuJoCo Simulation | Done (model + scripted gait works) |
| 9 | RL Training | **In progress** (pipeline works, training on laptop) |
| - | Voice Companion | **Working** (buddy/ — Realtime API + function calling + long-term memory) |
| - | Person Tracking | **Working** (YuNet face + TFLite person fallback + MOSSE + SORT + SFace face ID) |
| - | Room Awareness | **Working** (who's here → LLM context, voice commands: "who can you see?") |
| - | Personality v3 | **Working** (valence-arousal emotion, needs system, touch/departure/stranger hooks, care rituals) |
| - | Safety Laws | **Working** (Three Laws in LLM prompt, volume cap at 80%) |
| - | Spatial Memory | **Working** (absolute angular tracking, distance bins, occlusion persistence, scene descriptions) |
| - | Behavior Engine | **Working** (priority state machine: GREET/TRACK/SEARCH/REST/SLEEP, LED ownership, FaceFollower mode control) |
| - | Smart Arrivals | **Working** (identity-aware GREET: Alice=excited, family=warm, known=friendly, stranger=curious) |
| - | Memory v2 | **Working** (semantic per-person facts + episodic session summaries + combined extraction) |
