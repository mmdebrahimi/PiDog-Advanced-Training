# Person Tracking & Identification System for PiDog

> Complete vision pipeline: detect, track, identify, and respond to people — from ground-level CSI camera on a Pi 4 robot dog companion.

---

## Problem Statement

PiDog sits ~10cm off the ground. A child's face is ~100cm up. The camera's default angle sees floor/furniture, not faces. The dog needs to orient toward people, find their face, track them smoothly, know who they are, and tell the voice companion who's in the room — all on a Pi 4 with no GPU at ~10 FPS alongside a real-time voice session.

## Design Decisions

### D1: Layered search strategy (sound → face → body → sweep)

**Decision:** Five priority layers: (1) default head tilt up 30°, (2) sound direction snap toward voice, (3) face tracking, (4) body tracking when no face, (5) slow yaw sweep as fallback.

**Rationale:** Mimics real dog behavior. Sound sensor gives instant orientation; camera provides precision. Sweep is last resort.

**Trade-off:** Sound direction only works when someone is talking. Mitigated by body detection fallback.

### D2: Two-stage detection (TFLite person + Haar face)

**Decision:** TFLite SSD MobileNet for person detection (~15 FPS), then Haar cascade on person ROI for face detection (every 3rd frame). HeadEstimator infers head at top 12% of person bbox when no face visible.

**Rationale:** Person detection works at any angle; face detection needs a frontal view. Two-stage is faster than full-frame Haar and more robust. Existing `detect.tflite` model in vilib/workspace meant no download needed.

**Trade-off:** Haar cascade is noisy. Mitigated by SORT tracker smoothing + Kalman coasting.

### D3: Detection/servo thread split

**Decision:** Detection thread runs at ~10 FPS (as fast as TFLite allows). Separate servo thread runs at 30 Hz, reading the latest target position and sending smooth head_move commands.

**Rationale:** Single-threaded loop capped servo updates at 6 FPS (TFLite takes 100-180ms). Thread split gives 5x smoother servo motion. SORT tracker's Kalman predictions provide interpolation between detections.

**Trade-off:** Adds shared-state complexity. Mitigated by `_servo_lock` and `_state_lock` snapshot pattern.

### D4: OpenCV SFace for face identification (not dlib/InsightFace)

**Decision:** OpenCV's built-in `FaceRecognizerSF` (SFace model, 128-dim embeddings, 37MB) with JSON database at `~/.config/pidog/known_faces.json`.

**Rationale:** Built into OpenCV 4.13 (already installed). 200-400ms per embedding. dlib takes 3-4s. InsightFace models were behind auth walls. SFace auto-downloads from OpenCV Zoo if missing.

### D5: Proportional + EMA servo control (no PID)

**Decision:** Map pixel error to angular error via camera FOV (62°/640px), apply 35% proportional correction per frame, smooth with adaptive EMA (α=0.6 lockon, 0.3 tracking, 0.15 sweep).

**Rationale:** PID caused overshoot in the camera feedback loop (servo moves → face shifts → error decreases naturally). Proportional + EMA is simpler, stable, and physically grounded. Tested with simulated feedback loop before deployment.

### D6: CSI camera outputs BGR despite RGB888 config

**Decision:** Don't convert RGB→BGR for OpenCV display. Pass frames directly to `imshow()`.

**Rationale:** OV5647 CSI via picamera2 with `format: "RGB888"` actually outputs BGR. Converting RGB→BGR created a blue hue. Discovered during first hardware test.

### D7: Yaw limited to ±55° (not ±80°)

**Decision:** Narrow yaw servo range from hardware max ±80° to ±55°. Sweep range ±45°.

**Rationale:** ±80° yaw pulled the CSI ribbon cable loose, causing I/O errors and requiring camera reconnection. ±55° is safe for the cable.

## Implementation Summary

### Files Created
| File | Lines | Purpose |
|------|-------|---------|
| `buddy/servo_controller.py` | 130 | Proportional + EMA servo control |
| `buddy/detectors.py` | 180 | PersonDetector (TFLite), FaceDetector (Haar), HeadEstimator |
| `buddy/tracker.py` | 210 | SORT tracker (Kalman + Hungarian assignment) |
| `buddy/face_id.py` | 350 | Face embeddings (SFace), JSON database, async ID worker, CLI enrollment |
| `buddy/room_awareness.py` | 180 | Who's here, where last seen, LLM context summaries |

### Files Modified
| File | Changes |
|------|---------|
| `buddy/face_follower.py` | Two-stage detection, SORT integration, thread split, face ID, logging, video overlay |
| `buddy/companion.py` | Room awareness integration, personalized greetings, --video flag |
| `buddy/realtime_voice.py` | Dynamic PulseAudio, update_instructions, who_is_here + remember_face voice tools |

### Architecture

```
Detection Thread (~10 FPS):
  Camera → PersonDetector (TFLite) → FaceDetector (Haar, every 3rd frame)
    → SORT Tracker → face-to-track matching → FaceIDWorker (async)
    → write servo target + shared state

Servo Thread (30 Hz):
  Read servo target → proportional + EMA → head_move()

Companion Main Loop (every 2s):
  Read shared state → RoomState.update() → LLM instruction update (every 10s)

Voice Thread (Realtime API):
  Audio I/O + tool handling (who_is_here, remember_face, perform_action, go_to_sleep)
```

## Verification

1. `QT_QPA_PLATFORM=xcb python3 -m buddy.face_follower --log` — tracking with video overlay + CSV log
2. `python3 -m buddy.face_id --enroll "Alice"` — live preview enrollment
3. `python3 -m buddy.face_id --list` — verify known faces database
4. `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video` — full companion with tracking + voice
5. Ask "who can you see?" — dog responds with recognized names
6. Say "remember my face, I'm Alice" — voice-triggered enrollment

## Known Issues / Future Work

- I2S speaker doesn't produce audio on this Robot HAT v4 — using HDMI; plan to add Bluetooth speaker
- Wake-from-sleep WebSocket may stop transcribing — untested since tracking was added
- Detection thread at ~10 FPS could be faster with model quantization or frame skipping
- No multi-room tracking (dog is stationary on desk in safe mode)
- Alice hasn't tested yet — need Bluetooth speaker first for the magic moment
