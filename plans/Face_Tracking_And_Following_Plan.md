# Face Tracking and Person Following

> PiDog detects faces via USB webcam and tracks them with head servos, optionally walking toward the person.

---

## Problem Statement

The user wants the PiDog to see faces and follow people — a core feature for the companion dog experience. The CSI camera is physically connected but not detected by the Pi. The USB webcam (eMeet C960) works as a full video camera via picamera2. SunFounder's vilib library hangs when using the USB webcam, so we bypass it and use picamera2 + OpenCV directly.

## Design Decisions

### D1: picamera2 + OpenCV directly, bypass vilib

**Decision:** Use picamera2 for camera capture and OpenCV Haar cascade for face detection, bypassing vilib entirely.

**Rationale:** vilib's `camera_start()` hangs indefinitely when using the USB webcam (it was designed for CSI cameras). picamera2 works perfectly with the USB webcam (confirmed: 640x480 RGB frames at full speed). OpenCV's Haar cascade is the same detector vilib uses internally.

**Trade-off:** We lose vilib's web streaming view (`http://<ip>:9000/mjpg`) and its other detection modes (color, object, pose). Can add web streaming later with Flask if needed.

### D2: Head-only tracking by default, body following optional

**Decision:** Face follower defaults to head-only tracking (`follow_mode=False`). Body following (walking toward person) is enabled separately.

**Rationale:** Safe for desk testing — the dog won't walk off the table. Body following requires the dog to be on the floor. During voice conversation, head-only tracking is appropriate.

### D3: Largest face wins

**Decision:** When multiple faces are detected, track the largest one (closest person).

**Rationale:** Simple, works well for the primary use case (one child interacting with the dog). The largest face is the most engaged person.

## Implementation — What Was Built

### `buddy/face_follower.py` (new)

**Class: `FaceFollower`** — background thread running at 15Hz

| Method | Purpose |
|--------|---------|
| `start()` | Start camera + face detection thread |
| `stop()` | Stop tracking (camera stays open) |
| `close()` | Full shutdown including camera |
| `set_follow_mode(bool)` | Enable/disable body walking |
| `is_tracking()` | Currently tracking a face? |
| `get_face_info()` | Returns {x, y, w, n} of current face |
| `center_head()` | Return head to center |

**Head tracking:** Proportional control from SunFounder's `7_face_track.py` — adjusts yaw/pitch based on face offset from frame center. Gains: `YAW_GAIN=0.5`, `PITCH_GAIN=1.0`.

**Body following:** From SunFounder's `13_ball_track.py` pattern:
- Face width < 120px (far) → walk forward or turn toward face
- Face width > 280px (close) → stop
- Yaw > ±30° → turn body instead of just head

**Face lost timeout:** If no face for 2 seconds, centers head and stops tracking.

### Prerequisites installed

- `opencv-python-headless` 4.13.0 — face detection
- vilib install script run — Haar cascade model copied to `/opt/vilib/`
- picamera2 confirmed working with USB webcam at 640x480

### Standalone test command

```bash
cd ~/pidog_lab && python3 -m buddy.face_follower
```

## Not yet done

- [ ] Integration with voice companion (`main.py`) — face tracking during conversation
- [ ] CSI camera troubleshooting (ribbon cable may need reseating)
- [ ] Web streaming view (Flask) for remote monitoring

## Verification

1. `python3 -m buddy.face_follower` — dog sits, head follows face left/right/up/down
2. Face detection works: "Face: x=320, y=240, w=150" printed when face visible
3. Face lost: head returns to center after 2 seconds
4. Body follow (when enabled, dog on floor): walks toward person, stops at ~30cm
