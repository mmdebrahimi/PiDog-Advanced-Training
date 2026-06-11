# Spatial Memory & Object Permanence for PiDog

## Context

Nounou currently has a shallow spatial model — it knows "Alice is to your left" based on raw servo angles, but forgets her position 1.5 seconds after she leaves the frame. There's no object permanence (if Alice walks behind a chair, the dog thinks she vanished), no distance estimation, no trajectory memory, and no ability to detect objects other than people. This plan adds a spatial memory system that gives Nounou a "mental map" of its environment.

Research shows the highest-value features for a Pi 4 desk-mounted robot are: (1) extended occlusion persistence via Kalman prediction, (2) absolute angular position tracking, (3) rich spatial scene descriptions for the LLM, and (4) multi-class object detection.

## Current State

| Component | What exists | Gap |
|-----------|-------------|-----|
| SORT tracker (`tracker.py`) | Kalman 7D state, `max_age=15` (~1.5s), persistent IDs | Tracks die too fast, no occlusion persistence |
| Room awareness (`room_awareness.py`) | `PersonState(last_yaw, last_pitch, last_seen, visible)` | Only stores last servo angle, no absolute position, no history |
| Face follower (`face_follower.py`) | `get_tracked_people()` returns `[{id, name, bbox}]`, 10 FPS | Only exposes actively-detected tracks, not coasting ones |
| Servo controller (`servo_controller.py`) | H_FOV=62°, V_FOV=49°, 0.0969 deg/px | Pixel-to-angle conversion exists but not used for spatial memory |
| Detectors (`detectors.py`) | TFLite SSD MobileNet, person-only (COCO class 0) | No object detection |

## Implementation — 4 Phases

### Phase 1: Angular Position Tracking

**New file: `buddy/spatial_memory.py`** (~200 lines)

Core data structure:
```python
@dataclass
class AngularPosition:
    abs_yaw: float        # servo_yaw + pixel_offset_yaw
    abs_pitch: float      # servo_pitch + pixel_offset_pitch
    distance_bin: str     # "near" / "medium" / "far" from bbox height
    timestamp: float

class SpatialPersonState:
    name: str
    positions: deque(maxlen=20)     # circular buffer of recent positions
    last_velocity: (vyaw, vpitch)   # degrees/sec
    last_known: AngularPosition
    disappeared_at: float | None
```

Key functions:
- `pixel_to_absolute_angle(cx, cy, servo_yaw, servo_pitch)` — converts detection + servo state to absolute room-relative angle
- `bbox_to_distance_bin(bbox_h)` — near (>300px), medium (150-300px), far (<150px)
- `update(tracked_people, servo_yaw, servo_pitch)` — records angular positions per person
- `predict_position(name)` — extrapolate from last velocity for up to 10s

**Modify `buddy/room_awareness.py`:**
- Extend `PersonState` with `last_abs_yaw`, `last_abs_pitch`, `distance_bin`
- `update()` computes absolute angles: `abs_yaw = servo_yaw + (cx - 320) * 0.0969`
- `get_summary()` uses absolute yaw for direction + distance bin

**Modify `buddy/companion.py`:**
- Feed `spatial_memory.update()` from main loop alongside room updates

### Phase 2: Occlusion Persistence

**Modify `buddy/tracker.py`:**
- Increase `max_age` from 15 to 100 (~10 seconds of Kalman coasting)

**Modify `buddy/face_follower.py`:**
- `get_tracked_people()` already includes bbox; add a `get_coasting_tracks()` that returns tracks with `0 < time_since_update <= 30` (3s window)
- Coasting tracks feed room_awareness for presence but do NOT drive servo targeting

**Modify `buddy/room_awareness.py`:**
- Accept coasting tracks in `update()`, mark as `visible=True, coasting=True`
- When track dies, freeze last-known angular position from Phase 1
- Existing `PRESENCE_TIMEOUT=60s` provides long-term "still here" memory

**Add to `buddy/spatial_memory.py`:**
- `predict_position(name)` — uses last velocity to extrapolate for 10s, then freezes
- `get_predicted_direction(name)` — "Alice was moving to your left"

### Phase 3: Rich Spatial Scene Description for LLM

**Add to `buddy/spatial_memory.py`:**
- `get_scene_description()` — generates natural language from position history:
  - "Alice is sitting to your left, nearby, and has been there for a minute."
  - "Dad was in front of you but walked away 30 seconds ago, moving to your right."
  - "No one is around — you last saw Alice to your left 2 minutes ago."
- Max 2-3 sentences (stays within 500-word LLM context budget)

**Modify `buddy/memory_compiler.py`:**
- Replace raw room summary with `spatial_memory.get_scene_description()` in VISION section

**JSON persistence: `~/.config/pidog/spatial_memory.json`:**
- Stores per-person last-known positions and "typical positions" (weighted moving average)
- Enables: "Alice usually sits to your left"
- Same atomic-write pattern as social_graph.json

### Phase 4: Multi-Class Object Detection (Stretch)

**Add to `buddy/detectors.py`:** new `ObjectDetector` class
- Uses `efficientdet_lite0.tflite` (already on disk in vilib/workspace/)
- 320x320 input, 90-class COCO output with NMS post-processing
- Filter to indoor classes: chair, couch, table, TV, laptop, book, cup, bottle
- Returns `[(x, y, w, h, class_name, confidence)]`

**Modify `buddy/face_follower.py`:**
- Run object detection every 5th frame (amortized cost ~21ms/frame)
- Object detections stored in shared state, NOT fed to SORT tracker
- Person detection continues at every frame using current fast SSD model

**Add to `buddy/spatial_memory.py`:** object map
- Store detected objects with angular positions, update with EMA
- Include in scene description: "There's a cup on the table in front of you"

**Performance impact:** ~93ms current → ~106ms every 5th frame = ~9 FPS (acceptable)

## Dependency Graph

```
Phase 1 (Angular Positions)  ←  foundation
    ↓
Phase 2 (Occlusion)  ←  needs Phase 1 for angular storage
    ↓
Phase 3 (Scene Descriptions)  ←  needs Phase 1 + 2

Phase 4 (Object Detection)  ←  independent, feeds into Phase 1's spatial_memory
```

## Resource Budget

| Component | RAM | CPU/frame |
|-----------|-----|-----------|
| Angular position history (20 pos × 10 people) | ~16 KB | negligible |
| Extended SORT max_age (100 vs 15) | ~6 KB | <1ms |
| Spatial memory JSON | ~4 KB disk | save every 60s |
| Object detector (Phase 4 only) | ~8 MB model | 106ms every 5th frame |

## Verification

1. Start companion → spatial_memory initializes, prints "Spatial memory loaded"
2. Alice appears → absolute angular position computed, distance bin assigned
3. Alice walks left → velocity tracked, position history builds up
4. Alice leaves frame → Kalman prediction continues for ~10s, "Alice was moving left"
5. Ask "where is Alice?" → rich spatial response: "She was to your left, nearby, about 30 seconds ago"
6. Alice returns → re-identified by face, position history resumes
7. After 60s absence → "I haven't seen Alice in a while, she was last to your left"
8. `get_scene_description()` produces 2-3 sentence spatial context for LLM
9. (Phase 4) Objects detected → "There's a chair to your right"
