# Future Features

## High Priority

### Recording/Playback System
Date: 02/04/2026
Log joint commands + IMU at 50Hz into a format directly usable as RL training data. Every manual experiment becomes training signal. Bridges Phase 5 (logging) with Phase 9 (RL).

### Automated Joint Sweep Regression Check
Date: 02/04/2026
After initial manual joint mapping, create an automated script that sweeps all joints and logs IMU response. Useful as a regression check after library updates or hardware changes.

## Medium Priority

### Vision-Based RL
Date: 02/04/2026
User is adding a camera module. `vilib` is installed. Explore vision as an observation input for RL training alongside proprioception (IMU + joint angles). Requires camera integration into the Gymnasium environment observation space.

### Domain Randomization for Sim-to-Real
Date: 02/04/2026
Implement domain randomization (action delays, observation noise, friction variation) to improve policy transfer from simulation to physical robot. Defer until basic policy walks in sim.

## Low Priority

### STEP File Mesh Extraction
Date: 02/04/2026
SunFounder provided full 3D STEP assembly (`sim/pidog-总体装配-2024-12-5.STEP`, 110MB, SolidWorks). Open in FreeCAD on desktop to extract STL meshes per body part for visual fidelity in MuJoCo. Also useful for precise mass/inertia calculation from volumes.

### Curriculum Learning for Gait
Date: 02/04/2026
After basic forward walking works, add curriculum: flat → slight slope → rough terrain. Gradually increase difficulty during training for more robust gaits.

## Nice to Have

### Bluetooth Speaker Auto-Detection
Date: 05/04/2026
When a Bluetooth speaker is paired to the Pi, auto-detect it as the audio output device. Fall back to HDMI if no BT device found. Enables audio from the dog itself for Alice's first interaction.

### Multi-Person Conversation Awareness
Date: 05/04/2026
When multiple people are in the room (tracked by SORT + face ID), the dog could address them by name and follow the speaker. Requires correlating sound direction with tracked person positions. Room awareness already tracks who's here — this extends it to "who is speaking."

### Voice Companion V2 — Emotional State
Date: 04/04/2026
**Partially implemented (2026-04-05):** `personality.py` now has mood that evolves between sessions (excitement scales with absence). Traits are fixed. Quirks injected into LLM context. Remaining: mood affecting action choices (needs Behavior Engine), speech tone changes (Realtime API voice is fixed per session).

### Behavior Engine
Date: 05/04/2026
Priority-based state machine that centralizes Nounou's decision-making. Evaluates inputs (room state, tracking, voice, touch, time of day) every 500ms and picks the highest-priority active behavior: GREET, TRACK, SEARCH, REST, SLEEP. Controls head target, body actions, LED patterns, and voice context. Plan at `plans/Behavior_Engine_Plan.md`.

### Episodic Memory (v2)
Date: 05/04/2026
Per-session episode summaries stored in `~/.config/pidog/episodic_memory/YYYY-MM-DD.json`. Enables "remember when..." conversations. Requires forgetting/compression for old episodes. Current flat memory + social graph is v1; this is the v2 upgrade.

### Adaptive Volume
Date: 05/04/2026
Measure ambient noise level via mic and adjust PulseAudio output volume dynamically. Louder in noisy rooms, quieter at night. Currently set to 100% at startup which is the simple fix.

### Local Wake Word for Sleep State
Date: 05/04/2026
When the dog is sleeping (after "goodnight"), the Realtime API WebSocket may stop transcribing audio. Need a local wake word detector (pvporcupine or openwakeword) that runs on the Pi during sleep mode to detect "hi nounou" and reconnect the WebSocket. This is the only remaining blocker for a complete sleep/wake cycle.

### Voice Companion V2 — Edge TTS (legacy pipeline only)
Date: 04/04/2026
Only relevant if reverting to the legacy 3-call pipeline. The Realtime API handles TTS natively.

### I2S Speaker as Primary Output
Date: 04/04/2026
I2S Robot HAT speaker confirmed not producing audio on this HAT v4 revision (tested 2026-04-05). Need physical speaker or Bluetooth alternative. The I2S MEMS mic is also untested.
