# Vision Pipeline Upgrade

> Improve face tracking smoothness by switching to YuNet, adding MOSSE inter-frame tracking, and tuning servo parameters — making the dog smoothly follow Alice instead of jittering.

---

## Problem Statement

The dog's head moves too much when tracking Alice. The current pipeline (TFLite person detection + Haar face detection at ~10 FPS + SORT tracker) has gaps between detections that cause the servo to coast briefly, then sweep away from Alice. When detection re-acquires, the head snaps back aggressively. The result is a jittery, hunting head motion instead of smooth eye contact.

Root causes:
- Haar cascade is poor at side faces, tilted faces, and ground-level angles
- No inter-frame tracking between 10 FPS detection cycles — servo gets no updates for ~100ms gaps
- Coast duration too short (0.5s), sweep too eager (3s), lock-on too aggressive (60% snap)
- No dead zone — servo moves even when Alice is centered in frame

## Design Decisions

### D1: Switch Haar to YuNet for face detection

**Decision:** Replace Haar cascade with OpenCV's YuNet (`cv2.FaceDetectorYN`) for face detection.

**Rationale:** YuNet model (`face_detection_yunet.onnx`, 337KB) is already downloaded in `buddy/models/`. It handles side faces, partial occlusion, and tilted angles far better than Haar — exactly the conditions a ground-level robot dog camera encounters. ~25 FPS on Pi 4 at 320x240.

**Trade-off:** Haar is slightly faster on Pi 4 due to optimized cascade operations, but its accuracy on non-frontal faces is much worse. YuNet is the better fit for this use case.

### D2: Add MOSSE inter-frame tracker

**Decision:** Use OpenCV's MOSSE tracker (`cv2.legacy.TrackerMOSSE_create()`) to track the face between detection frames, giving the servo smooth 30 Hz position updates.

**Rationale:** MOSSE runs at 450+ FPS (~2ms/frame), adding negligible latency. It fills the gap between 10 FPS detections with smooth position updates. This is the proven pattern used by successful face-following robot projects on Pi.

**Trade-off:** KCF is more accurate but slower (~100 FPS). Start with MOSSE; switch to KCF if drift is noticeable.

### D3: Keep person detection as fallback

**Decision:** Keep TFLite person detection but make face detection the primary path. Only fall back to body tracking (HeadEstimator) when no face is found for >2s.

**Rationale:** From ground level, the camera often sees Alice's body without her face (turned away, looking down). Dropping person detection entirely would lose the HeadEstimator fallback. But face detection should be prioritized since it gives better tracking targets.

### D4: Add dead zone

**Decision:** Don't move servos when the tracked face is within the center 10-15% of the frame.

**Rationale:** Eliminates micro-jitter when Alice is roughly centered. Zero cost, immediate improvement.

## Implementation Plan

### Step 1: Parameter tuning (existing plan)

**File:** `buddy/face_follower.py`, `buddy/servo_controller.py`

As described in `plans/Head_Tracking_Smoothing_Plan.md`:
- `TRACK_COAST_FRAMES`: 5 → 15
- `SWEEP_TIMEOUT`: 3.0 → 8.0
- `FACE_LOST_TIMEOUT`: 2.0 → 4.0
- `ALPHA_LOCKON`: 0.6 → 0.3

### Step 2: Switch Haar to YuNet

**File:** `buddy/detectors.py`

- Add `YuNetDetector` class using `cv2.FaceDetectorYN`
- Model path: `buddy/models/face_detection_yunet.onnx` (already on disk)
- Input size: 320x240 for speed
- Score threshold: 0.7
- Same output format as current `FaceDetector`: list of `(x, y, w, h)`

**File:** `buddy/face_follower.py`

- Replace `FaceDetector` with `YuNetDetector` in `__init__` and `_detect_tflite`
- Remove the "run face every 3rd frame" throttle — YuNet is fast enough to run every frame

### Step 3: Add dead zone

**File:** `buddy/face_follower.py` (detection loop)

- After computing servo target `(cx, cy)`, check if it's within center 10% of frame
- If within dead zone, don't update `_servo_target` — hold current position
- Dead zone: `abs(cx - FRAME_W/2) < FRAME_W * 0.05 and abs(cy - FRAME_H/2) < FRAME_H * 0.05`

### Step 4: Add MOSSE inter-frame tracker

**File:** `buddy/face_follower.py`

- When a face is detected, initialize MOSSE tracker on the face bbox: `tracker = cv2.legacy.TrackerMOSSE_create(); tracker.init(frame, bbox)`
- In servo thread (30 Hz): if detection thread hasn't updated target, call `tracker.update(frame)` to get predicted position
- Reset MOSSE tracker whenever detection provides a new bbox
- If MOSSE loses track (returns False), fall back to Kalman coast

This requires sharing the current frame between detection and servo threads (already available via `_latest_frame`).

## Verification

1. Start with video: `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video`
2. Stand in front — head should smoothly follow with minimal jitter
3. Turn head sideways — YuNet should still detect (Haar would lose the face)
4. Walk slowly across room — head should glide smoothly (MOSSE fills gaps)
5. Stand still, centered — head should NOT micro-jitter (dead zone)
6. Walk out of frame — sweep should start after ~8s, not 3s
7. Walk back in — head should glide to face, not snap (alpha 0.3)
8. Compare tracking log CSVs before/after: `python3 -m buddy.face_follower --log`
