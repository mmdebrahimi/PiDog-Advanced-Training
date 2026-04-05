# Plans Index
<!-- Auto-maintained by /save-plan. Do not edit manually. -->

## [plan_file: PiDog_Master_Roadmap_Plan.md] 2026-04-02
**Summary:** End-to-end robotics learning plan from hardware control through MuJoCo simulation and RL.
**Key decisions:**
- Collapse Phases 2 and 4 (API discovery and custom interface — already provided by SunFounder libraries)
- Thread-safe buffer API over direct servo calls
- Keep ROS 2 in plan as learning goal + simulation bridge
- Defer calibration until after joint mapping

---

## [plan_file: MuJoCo_Simulation_Pipeline_Plan.md] 2026-04-02
**Summary:** Build a MuJoCo model of PiDog, script a trot in sim, tune with system ID, then train locomotion with RL.
**Key decisions:**
- MuJoCo over Isaac Sim (CPU-only, runs on Pi 4, better Python API)
- Desktop for training, Pi for deployment (40 FPS vs ~400+ FPS)
- Position actuators for servo modeling
- Defer ROS 2 (not needed for MuJoCo pipeline)

---

## [plan_file: RL_Reward_Fix_And_Desktop_Training_Plan.md] 2026-04-03
**Summary:** Fix broken reward function, package sim for desktop, train walking policy on faster machine.
**Key decisions:**
- Fix reward before anything else (system ID on a falling policy is wasted work)
- Train on desktop, deploy on Pi
- Heavier alive bonus + termination penalty to fix "die quickly" incentive

---

## [plan_file: Policy_Training_And_Deployment_Plan.md] 2026-04-03
**Summary:** Train PPO walking policy on corporate laptop via email transfer, deploy to real PiDog.
**Key decisions:**
- Email-based file transfer (Zscaler blocks direct Pi↔laptop connection)
- Train on laptop, deploy on Pi

---

## [plan_file: Voice_Companion_Complete_Plan.md] 2026-04-04
**Summary:** Turn PiDog into an interactive talking companion for a 7-year-old, with ChatGPT conversation, physical behaviors, and long-term memory.
**Key decisions:**
- OpenAI TTS API over pico2wave (warm voice for child bonding, $0.02/day)
- Whisper API for STT (local Whisper too slow on Pi 4)
- Wake word via transcript check (simple, no extra dependencies)
- Long-term memory via markdown file updated by ChatGPT summarization on shutdown

---

## [plan_file: Face_Tracking_And_Following_Plan.md] 2026-04-04
**Summary:** PiDog detects faces via USB webcam and tracks them with head servos, optionally walking toward the person.
**Key decisions:**
- picamera2 + OpenCV directly, bypass vilib (vilib hangs on USB webcam)
- Head-only tracking by default, body following optional
- Largest face wins when multiple detected

---

## [plan_file: Person_Finding_Strategy_Plan.md] 2026-04-05
**Summary:** Layered approach to find and track a person from ground level: sound direction → head snap + tilt up → face detection → sweep fallback.
**Key decisions:**
- Sound direction sensor as primary person-finding signal (instant orientation toward voice)
- Default head pitch tilted up 20° (humans are above the dog)
- Five-layer search: default tilt → voice snap → face track → sweep → return to last known

---

## [plan_file: Person_Tracking_Complete_System_Plan.md] 2026-04-05
**Summary:** Complete vision pipeline for PiDog: detect, track, identify, and respond to people from ground-level CSI camera on Pi 4.
**Key decisions:**
- Two-stage detection: TFLite SSD person + Haar face on ROI (no model download needed)
- Detection/servo thread split: 10 FPS detection + 30 Hz servo for smooth tracking
- OpenCV SFace for face ID (built-in, 128-dim embeddings, JSON database)
- Proportional + EMA servo control (PID caused overshoot in camera feedback loop)
- Yaw limited to ±55° to protect CSI ribbon cable
- Voice commands: who_is_here + remember_face tools for Realtime API

---

## [plan_file: Behavior_Engine_Plan.md] 2026-04-05
**Summary:** Centralize Nounou's decision-making into a priority-based behavior engine that orchestrates head tracking, actions, LEDs, and voice context.
**Key decisions:**
- Priority-based state machine, not LLM orchestrator (instant, deterministic)
- Behaviors as skill sequences, not agent frameworks
- Start with 5 behaviors: GREET, TRACK, SEARCH, REST, SLEEP

---
