# Head Tracking Smoothing

> Reduce unnecessary head movement when tracking Alice by tuning coast, sweep, and servo smoothing parameters.

---

## Problem Statement

When tracking Alice, the dog's head moves too much — jittery re-acquisitions, premature sweeps when detection briefly drops, and aggressive snapping back when the face reappears. Once the dog finds Alice, it should smoothly follow her with its "eyes" instead of hunting around.

Root cause is a cascading failure loop when face detection drops briefly (Alice turns her head, shadow, lighting change):
1. Coast is too short (5 frames / 0.5s) — gives up on Kalman prediction too early
2. Sweep kicks in after only 3s — pans the head away from where Alice likely still is
3. Lock-on alpha is too aggressive (0.6) — snaps 60% toward new target in one frame when re-acquiring
4. Face lost timeout is too short (2s) — declares tracking lost before the brief dropout resolves

## Implementation Plan

### Step 1: Increase coast duration

**File:** `buddy/face_follower.py`

- Change `TRACK_COAST_FRAMES` from `5` to `15` (~1.5s of Kalman prediction at 10 FPS)
- This keeps the servo following the predicted position during brief detection dropouts

### Step 2: Increase sweep timeout

**File:** `buddy/face_follower.py`

- Change `SWEEP_TIMEOUT` from `3.0` to `8.0` seconds
- Dog stays pointed at last known position longer before giving up and sweeping

### Step 3: Increase face lost timeout

**File:** `buddy/face_follower.py`

- Change `FACE_LOST_TIMEOUT` from `2.0` to `4.0` seconds
- More patient before declaring tracking lost

### Step 4: Smooth lock-on re-acquisition

**File:** `buddy/servo_controller.py`

- Change `ALPHA_LOCKON` from `0.6` to `0.3` — less aggressive snap when re-acquiring
- This makes the head glide toward the re-detected face instead of jumping

## Verification

1. Start companion with video: `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video`
2. Stand in front of the dog — head should smoothly follow
3. Turn away briefly (2-3s) — head should hold position, not sweep
4. Turn back — head should glide smoothly to re-acquired face, not snap
5. Walk out of frame — sweep should start after ~8s, not 3s
6. Compare head movement smoothness against pre-change behavior
