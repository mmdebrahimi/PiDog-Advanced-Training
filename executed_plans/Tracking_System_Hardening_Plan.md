# Tracking System Hardening — Technical Plan

> Fix critical and medium issues from brainstorm review: dual Kalman divergence, face matching, instruction spam, dead code, model setup.

## Problem Statement

The 4-phase person tracking system works end-to-end (room awareness recognized "Dad" on first run) but has: redundant Kalman filters causing prediction divergence during coasting, strict face-to-track matching that fails for moving people, excessive LLM instruction updates every 2s, dead code, and missing model download for fresh clones.

## Codebase Context

- `buddy/servo_controller.py` (284 lines) — KalmanFilter2D (lines 13-68), unused PIDController (lines 70-124), ServoController.predict() (line 262)
- `buddy/face_follower.py` (634 lines) — face-to-track containment (lines 441-447), Kalman coasting (lines 472-478), tracking loop
- `buddy/companion.py` (206 lines) — main loop update_instructions (line 188), Room print (line 191)
- `buddy/face_id.py` (331 lines) — FaceEmbedder loads SFace model, no download check
- No test suite in project

## Implementation Steps

### Step 1: Remove PIDController dead code
Files: buddy/servo_controller.py
Depends on: none

**What changes:**
- servo_controller.py — delete `PIDController` class (lines 70-124)

**Key details:**
- Class is defined but never imported or instantiated (verified via grep)
- 55 lines of dead code

**Test strategy:**
- `from buddy.servo_controller import ServoController` still works

### Step 2: Fix coasting to use SORT track prediction
Files: buddy/face_follower.py
Depends on: none

**What changes:**
- face_follower.py lines 472-478 — replace `self._servo.predict()` with SORT tracker's predicted center
- Store `_last_track_id` when tracking, use it to find the right track during coasting
- Call `track.center` for the predicted position instead of servo's internal Kalman

**Key details:**
- Currently servo Kalman and SORT Kalman predict independently → diverge during coast
- SORT already predicts each track forward in `_tracker.update()`
- Track center is available via `track.center` property (tracker.py line 95)

**Test strategy:**
- Run with --log, verify coast frames show smooth yaw_delta (no jumps on coast→tracking transition)

### Step 3: Fix face-to-track matching with distance-based fallback
Files: buddy/face_follower.py
Depends on: Step 2

**What changes:**
- face_follower.py lines 441-447 — replace strict bbox containment with center-distance matching
- For each face, find the track whose bbox center is closest to the face center
- Match if distance < half the track bbox diagonal

**Key details:**
- Current strict containment fails when SORT bbox is predicted forward but face is from 1-2 frames ago
- Distance matching is robust to bbox jitter and timing mismatches

**Test strategy:**
- Run with --log, verify face ID results appear consistently

### Step 4: Rate-limit room state updates and fix console spam
Files: buddy/companion.py
Depends on: none

**What changes:**
- Add 10-second minimum interval between `update_instructions()` calls
- Only print "Room:" when the who list changes from last print
- Track `last_instruction_time` and `last_who_printed` state variables

**Key details:**
- Currently sends session.update every 2s when room state changes (even minor position shifts)
- Console prints "Room: Dad" continuously — should only print on arrival/departure

**Test strategy:**
- Run companion, verify "Room: Dad" prints once on arrival
- Verify no repeated prints while person stays visible

### Step 5: Add model download check for face ID
Files: buddy/face_id.py
Depends on: none

**What changes:**
- FaceEmbedder.__init__ — check if SFace model exists; if missing, auto-download from OpenCV Zoo
- Add `_ensure_model(path, url)` helper that downloads if file doesn't exist
- Also check YuNet model for FaceDetectorYN (future use)

**Key details:**
- buddy/models/ is gitignored (37MB SFace + 0.2MB YuNet)
- Download URLs proven to work: `github.com/opencv/opencv_zoo/raw/main/models/...`
- Graceful fallback: if download fails, print clear error with manual instructions

**Test strategy:**
- Rename model file temporarily, verify auto-download triggers
- Verify face ID works after download

## Execution Preview

```
Wave 0 (3 parallel):  Step 1 — dead code, Step 4 — rate limit, Step 5 — model check
Wave 1 (1 sequential): Step 2 — coasting fix
Wave 2 (1 sequential): Step 3 — face matching (depends on Step 2, same file)

Critical path: Step 2 → Step 3 (2 waves for face_follower.py changes)
Max parallelism: 3 agents
```

Note: Steps 2 and 3 both modify face_follower.py so they must be sequential. Steps 1, 4, 5 touch different files and can run in parallel.

## Risk Flags
- Steps 2 and 3 both modify face_follower.py — sequenced as Wave 1 → Wave 2
- Step 5 makes network calls — graceful fallback required if offline
- No test suite — verification is manual (run face_follower with --log)

## Verification
1. `python3 -c "from buddy.servo_controller import ServoController; print('OK')"` — Step 1
2. `QT_QPA_PLATFORM=xcb python3 -m buddy.face_follower --log` — Steps 2, 3 (check log for smooth coasting)
3. `python3 -m buddy.companion` — Step 4 (verify "Room:" prints only on change)
4. Rename `buddy/models/face_recognition_sface.onnx`, run face_id — Step 5 (verify auto-download)
