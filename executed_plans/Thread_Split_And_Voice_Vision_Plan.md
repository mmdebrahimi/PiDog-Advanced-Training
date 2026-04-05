# Thread Split + Servo Cleanup + Voice Vision Commands — Technical Plan

> Decouple detection from servo control for 30 Hz smooth tracking, remove redundant Kalman, add vision voice commands.

## Problem Statement

The tracking loop runs detection + servo control synchronously at ~6 FPS (TFLite takes 100-180ms). The servo only updates when detection completes, causing visible jerkiness. Additionally, the servo controller has a redundant KalmanFilter2D that duplicates SORT's per-track Kalman, and the voice companion has no way to tell the user who it can see.

## Codebase Context

- `face_follower.py` (634 lines): single-threaded loop at lines 417-531 does capture→detect→track→servo→overlay→log sequentially
- `servo_controller.py` (229 lines): KalmanFilter2D (lines 13-68) + ServoSmoother + ServoController — Kalman is redundant with SORT
- `realtime_voice.py` (407 lines): tools defined at lines 42-73, handled in `_receive_events` lines 245-353
- `companion.py` (216 lines): reads `tracker.yaw`, `tracker.pitch`, `get_tracked_people()` from main loop — **no thread safety locks**
- `room_awareness.py` (180 lines): `who_is_here()`, `get_summary()` already exist

Race conditions exist: companion reads yaw/pitch/tracking state from tracking thread with no locks.

## Implementation Steps

### Step 1: Add thread-safe shared state to FaceFollower
Files: buddy/face_follower.py
Depends on: none

**What changes:**
- Add a `threading.Lock` (`_state_lock`) protecting all shared tracking state
- Create a `_TrackingState` dataclass holding: target (cx, cy, w, source), faces, persons, tracks, yaw, pitch, tracking flag
- All writes to shared state go through `_update_state()` which acquires the lock
- All reads (`get_face_info`, `get_tracked_people`, `yaw`/`pitch` properties) acquire the lock
- This is a prerequisite for the thread split — makes the existing single-thread code thread-safe first

**Key details:**
- The `_frame_lock` already protects video frames — this new lock is for tracking state
- Keep yaw/pitch as properties (not direct attributes) so the lock is always acquired
- Companion's reads in main loop become safe immediately

**Test strategy:**
- Run `face_follower --log` — verify tracking still works identically
- No behavioral change, only thread safety

### Step 2: Split detection and servo into separate threads
Files: buddy/face_follower.py
Depends on: Step 1

**What changes:**
- Replace single `_tracking_loop` with two threads:
  - `_detection_thread` (~10 FPS): capture → detect → update SORT tracker → write shared state
  - `_servo_thread` (30 Hz): read latest target from shared state → proportional + EMA → head_move
- Detection thread writes target position to shared state via `_update_state()`
- Servo thread reads target position, computes servo angles, sends head_move
- Servo thread interpolates between detections using the SORT track's predicted center
- Sound direction and sweep logic stay in the detection thread (they modify tracking state)
- Overlay rendering stays in the detection thread (it needs frame + detections)

**Key details:**
- Servo thread runs at 30 Hz (33ms interval) — 5x faster than detection
- Between detections, servo thread uses last known target + time-based interpolation via SORT prediction
- Detection thread calls `_tracker.update()` which advances Kalman predictions
- Servo thread calls `_tracker.get_track(id).center` for interpolated position
- Both threads stopped by `self._running = False`

**Test strategy:**
- Run `face_follower --log` — verify FPS shows ~10 for detection, servo updates visible at ~30 Hz in log
- Slow pan test: head follows smoothly without stepping
- Quick movement: faster response than before

### Step 3: Remove redundant KalmanFilter2D from servo controller
Files: buddy/servo_controller.py
Depends on: Step 2

**What changes:**
- Remove `KalmanFilter2D` class entirely (lines 13-68)
- Remove Kalman usage from `ServoController.update()` — it now receives pre-smoothed positions from SORT
- Remove `ServoController.predict()` method (no longer needed — SORT handles prediction)
- ServoController becomes: pixel error → FOV mapping → proportional correction → EMA smooth
- ~60 lines removed

**Key details:**
- SORT's per-track Kalman already smooths detection noise
- Servo controller only needs: proportional gain (0.35) + EMA smoothing
- The `reset()` method simplifies — only resets EMA smoothers and angles

**Test strategy:**
- Run `face_follower --log` — verify tracking quality unchanged
- Verify servo controller still initializes: `from buddy.servo_controller import ServoController`

### Step 4: Add "who is here" voice command
Files: buddy/realtime_voice.py, buddy/companion.py
Depends on: none

**What changes:**
- realtime_voice.py: Add `WHO_IS_HERE_TOOL` definition (function tool, no parameters)
- realtime_voice.py: Add to tools list in session config (line 207)
- realtime_voice.py: Handle in `_receive_events` — call `self._on_who_is_here()` callback
- realtime_voice.py: Add `on_who_is_here(callback)` registration method
- companion.py: Register callback that queries `room.get_summary()` and returns it as tool output
- The LLM can now call this tool when asked "who's here?" and get back "You can see: Dad."

**Key details:**
- Tool returns room summary string as function_call_output
- LLM uses the response to answer naturally ("I can see you, Dad!")
- Tool has no parameters — just queries current room state
- Must call `conn.response.create()` after sending output to trigger LLM response

**Test strategy:**
- Run companion, ask "who can you see?" — dog should respond with name
- Ask when no one is visible — should say "no one around"

### Step 5: Add "remember my face" voice command
Files: buddy/realtime_voice.py, buddy/companion.py
Depends on: Step 4

**What changes:**
- realtime_voice.py: Add `REMEMBER_FACE_TOOL` definition (function tool with `name` string parameter)
- realtime_voice.py: Add to tools list, handle in `_receive_events`
- realtime_voice.py: Add `on_remember_face(callback)` registration method
- companion.py: Register callback that calls `tracker.enroll_face(name)` and returns success/failure
- The LLM can now call this tool when someone says "remember my face, I'm Alice"

**Key details:**
- Tool takes `name` parameter (string)
- Calls `FaceFollower.enroll_face(name)` which captures from the current tracked face
- Returns success/failure — LLM responds "Got it, I'll remember you Alice!" or "I can't see your face right now"
- Only works if a face is currently being tracked

**Test strategy:**
- Run companion, say "remember my face, I'm Alice" — verify enrollment happens
- Check `python3 -m buddy.face_id --list` — Alice should appear

## Execution Preview

```
Wave 0 (2 parallel):  Step 1 — Thread-safe state, Step 4 — Who is here voice command
Wave 1 (2 parallel):  Step 2 — Thread split, Step 5 — Remember face voice command
Wave 2 (sequential):  Step 3 — Remove servo Kalman
```

Critical path: Step 1 → Step 2 → Step 3 (3 waves)
Max parallelism: 2 agents

Note: Steps 1→2→3 are sequential (all modify face_follower.py / servo_controller.py). Steps 4→5 are sequential (both modify realtime_voice.py + companion.py). But the two chains are independent.

## Risk Flags
- Steps 1, 2, 3 all modify face_follower.py — strictly sequential
- Steps 4, 5 both modify realtime_voice.py and companion.py — strictly sequential
- Thread split (Step 2) is the highest-risk change — shared state between detection and servo threads
- Step 2 changes the fundamental execution model — if it breaks, tracking stops entirely
- Step 3 depends on Step 2 being correct (removes Kalman that Step 2 makes redundant)

## Verification
1. `QT_QPA_PLATFORM=xcb python3 -m buddy.face_follower --log` — verify smooth tracking at 30 Hz servo rate
2. `python3 -m buddy.companion --video` — verify voice + tracking + video all work together
3. Ask "who can you see?" during companion — verify room awareness voice response
4. Say "remember my face, I'm Alice" — verify enrollment works via voice
5. Check log CSV: detection at ~10 FPS, servo at ~30 Hz, no large yaw_delta spikes
