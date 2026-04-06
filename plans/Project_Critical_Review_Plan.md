# Project Critical Review — Full State Assessment

> Critical review of all 9 PiDog plans after 4 days of development: what's solid, what has gaps, what's risky, and recommended priority order for next steps.

---

## Problem Statement

PiDog has two parallel tracks — a companion system (voice + vision + personality) and an RL locomotion pipeline (MuJoCo + PPO). After 4 days and 9 plans, the system has never run end-to-end with a real user. Hardware issues (undervoltage restarts, CSI camera disconnected, no speaker) block the first real demo with Alice. A critical review is needed to prioritize what to fix before Alice's first test.

## Critical Issues — Must Address

### C1: Undervoltage is a showstopper

**Finding:** Pi restarts randomly (`vcgencmd get_throttled = 0x50000` — undervoltage + throttling occurred). Only 3 minutes uptime observed. [grounded]

**Risk:** Corrupts JSON databases (known_faces, social_graph, personality) mid-write. Crashes during Alice's first interaction would be the worst possible outcome.

**Fix:** Get a proper 5V/5A PSU or separate the servo power rail. `face_id.py` uses atomic writes (tmp + `os.replace`) but `social_graph.py` and `personality.py` may not — verify all persistent stores use atomic writes.

### C2: CSI camera gone, USB camera untested with full pipeline

**Finding:** CSI camera not detected (ribbon cable pulled loose by head movement). USB webcam (eMeet C960) outputs RGB when configured as RGB888, but code assumes BGR (designed for CSI quirks). Face enrollment happened with blue-tinted preview. [grounded]

**Risk:** Alice's 5 enrolled face embeddings may be trained on color-distorted crops. SFace internally works on aligned/grayscale so embeddings are likely fine, but display and Haar detection could be affected.

**Fix:** Add RGB→BGR conversion for USB cameras. Re-enroll Alice after fix to be safe. Consider physically reseating CSI cable and taping it down as originally recommended.

### C3: No end-to-end test has ever completed

**Finding:** Session Summary states "Alice hasn't tested yet." Voice companion hit API quota errors. Face enrollment had wrong colors. System has never run all components together with a real user. [grounded]

**Fix:** Before any new feature work, run a full integration test: camera + tracking + face ID + voice + personality, all at once.

## Medium Issues — Should Address

### M1: Two parallel tracks competing for Pi resources

**Finding:** Companion track (camera + TFLite + voice + WebSocket) and RL track (policy inference at 50Hz) will eventually need to coexist on the same Pi 4. No plan addresses resource contention. [inferred]

### M2: Behavior Engine plan has no failure modes

**Finding:** Describes happy-path transitions (GREET→TRACK→SEARCH→REST→SLEEP) but doesn't address: GREET vs RESPOND conflict, mid-action preemption when new person arrives, wrong face ID (greets stranger as Alice). [grounded]

### M3: RL reward fix is designed but untested

**Finding:** Reward function fix (heavier alive bonus, termination penalty) is a reasonable direction but reward shaping typically takes 5-10 iterations. Email-based file transfer makes each iteration slow. [grounded]

## What's Solid — Survived Review Unchanged

- **Thread architecture** — detection/servo split at different rates is well-designed
- **SFace for face ID** — pragmatic, built into OpenCV, avoids dlib's 3-4s latency
- **SORT tracker** — proper Kalman + Hungarian assignment, not a hack
- **Atomic file writes** in face_id.py — crash-safe
- **Safe mode default** — smart for desk development
- **Memory/personality system** — social graph + personality + memory compiler is complete
- **Master roadmap philosophy** — "build up, never skip layers" is sound
- **MuJoCo over Isaac Sim** — correct for Pi 4 (CPU-only, native Python)

## Open Tradeoffs — Decisions for the User

### T1: Fix hardware first vs. push for Alice demo?

- **Case for hardware first:** Undervoltage crashes + no audio (quota exceeded, HDMI only) = bad first impression
- **Case for demo now:** Tracking + face ID works visually even without voice. A silent demo where the dog follows Alice's face could still be magical

### T2: Behavior Engine vs. Bluetooth speaker next?

- Session summary says both are "next session" priority
- **BT speaker** is more impactful for Alice (the dog can talk)
- **Behavior Engine** is more impactful for the system (structured decision-making)
- Recommendation: BT speaker first — Alice's reaction IS the roadmap, and she needs to hear the dog

### T3: Re-enroll Alice or trust SFace?

- SFace internally converts to grayscale for alignment, so BGR vs RGB may not affect embeddings
- But re-enrollment takes 30 seconds, so why risk it

## Implementation Plan — Recommended Priority Order

### Step 1: Fix power supply (hardware)
- Get 5V/5A USB-C PSU or separate servo power rail
- Verify all JSON writers use atomic writes (social_graph.py, personality.py)

### Step 2: Fix OpenAI billing
- Refresh API credits — voice is the core experience

### Step 3: Fix USB camera BGR conversion
- Add `cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)` after capture in `face_follower.py` and `face_id.py` when using USB camera
- Or: reseat CSI ribbon cable and tape it down

### Step 4: Re-enroll Alice
- `QT_QPA_PLATFORM=xcb python3 -m buddy.face_id --enroll "Alice"` after color fix

### Step 5: Add Bluetooth speaker
- Connect BT speaker, set as PulseAudio default sink
- Test TTS output through BT

### Step 6: Run Alice's first test
- `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video`
- Watch. Take notes. Don't intervene. Her reactions define what to build next.

### Step 7: Behavior Engine (after Alice feedback)
- Implement based on `plans/Behavior_Engine_Plan.md`
- Add failure mode handling (preemption, wrong ID, conflicts)

## Verification

1. Pi runs stable for 30+ minutes under full companion load (no undervoltage restarts)
2. Voice companion completes a full conversation with Alice (wake → talk → goodbye)
3. Face ID correctly identifies Alice by name during companion session
4. Dog tracks Alice's face smoothly as she moves
5. Audio plays through BT speaker (not HDMI)
