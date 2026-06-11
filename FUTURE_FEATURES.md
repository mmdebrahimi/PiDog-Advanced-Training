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

### Bluetooth Speaker
Date: 05/04/2026
Connect BT speaker so the dog has its own voice. Auto-detect as PulseAudio default sink, fall back to HDMI. Critical for Alice's first test — she needs to hear Nounou speak from the dog itself.

### Multi-Person Conversation Awareness
Date: 05/04/2026
When multiple people are in the room (tracked by SORT + face ID), the dog could address them by name and follow the speaker. Requires correlating sound direction with tracked person positions. Room awareness already tracks who's here — this extends it to "who is speaking."

### Voice Companion V2 — Emotional State
Date: 04/04/2026
**Implemented (2026-06-10):** Personality v3 with valence-arousal emotion, needs system, event hooks, care rituals, spontaneous behaviors. Mood-driven action selection via behavior engine (mood actions: wag tail if happy, howl if sad, etc.). Time-of-day awareness. Remaining: mood affecting speech tone (Realtime API voice is fixed per session).

### Behavior Engine
Date: 05/04/2026
**Implemented (2026-04-11):** Priority-based state machine in `buddy/behavior_engine.py`. 5 behaviors: SLEEP > GREET > TRACK > SEARCH > REST. Engine coordinates FaceFollower mode, LED patterns, personality hooks, and LLM context injection. Companion.py main loop reduced from ~100 lines to ~10 lines.

### Proactive Conversation Initiation
Date: 06/04/2026
Dog speaks first instead of only responding. Triggers: face detection without recent interaction ("Alice! I was thinking about you!"), time-based ("It's been two days!"), context callbacks ("Did you finish that drawing?"). Short, optional, never pushy. Research shows this is key for sustained engagement.

### Daily Ritual Slots
Date: 06/04/2026
Morning greeting, after-school check-in, bedtime wind-down ("What was the best part of today?"). Research shows engagement drops after week 2 unless robot embeds into daily routines. Use time-of-day triggers via cron or companion loop.

### Emotional Sound Layer
Date: 06/04/2026
Pre-recorded .wav files triggered by emotion state: contented sigh when petted, excited yip before speech, sleepy grumble when tired. Non-verbal sounds trigger stronger emotional responses than words. Zero compute cost — file playback alongside voice.

### Mini-Games
Date: 06/04/2026
Simon Says (dog does action, Alice copies), Teaching Tricks (pretend learning over 3 attempts), 20 Questions, Story Time (take turns). All achievable with existing 30 ActionFlow actions + voice.

### Multi-Class Object Detection
Date: 06/04/2026
Use existing `efficientdet_lite0.tflite` in vilib/workspace/ to detect chairs, cups, toys. Run every 5th frame (~9 FPS). Store in spatial memory. Plan at `plans/Spatial_Memory_Plan.md` Phase 4.

### Personality Drift Over Time
Date: 06/04/2026
Track interaction types in a JSON counter (petting frequency, game types, conversation topics). Over weeks, shift personality weights — if Alice reads to Nounou, develop a "bookworm" quirk. The dog becomes uniquely hers.

### Episodic Memory (v2)
Date: 05/04/2026
**Implemented (2026-06-10):** Three-layer memory: Soul (immutable personality), Semantic (per-person facts with dedup, milestones, topic counters in `semantic_memory.py`), Episodic (rolling 10 session summaries with emotional tone and key moments in `episodic_memory.py`). Combined single API call extraction at shutdown. Context injection includes "Last time you talked to Alice..." preamble.

### Battery-as-Hunger
Date: 06/04/2026
Map Pi voltage to personality hunger state. Low battery = "tummy rumbling", charging = "eating". Tamagotchi-style care mechanic that drives bonding through dependency.

### Adaptive Volume
Date: 05/04/2026
Measure ambient noise level via mic and adjust PulseAudio output volume dynamically. Louder in noisy rooms, quieter at night. Currently ramped to 80% at startup (child-safe cap).

### Local Wake Word for Sleep State
Date: 05/04/2026
When the dog is sleeping (after "goodnight"), the Realtime API WebSocket may stop transcribing audio. Need a local wake word detector (pvporcupine or openwakeword) that runs on the Pi during sleep mode to detect "hi nounou" and reconnect the WebSocket. This is the only remaining blocker for a complete sleep/wake cycle.

### Voice Companion V2 — Edge TTS (legacy pipeline only)
Date: 04/04/2026
Only relevant if reverting to the legacy 3-call pipeline. The Realtime API handles TTS natively.

### I2S Speaker as Primary Output
Date: 04/04/2026
I2S Robot HAT speaker confirmed not producing audio on this HAT v4 revision (tested 2026-04-05). Need physical speaker or Bluetooth alternative. The I2S MEMS mic is also untested.
