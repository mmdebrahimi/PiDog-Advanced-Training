# Session Summary & Next Steps Plan

> Complete record of the person tracking + personality system built in one session, plus prioritized next steps based on CEO review.

---

## Problem Statement

PiDog needed to find, track, identify, and respond to people — transforming from a stateless voice chatbot into a companion that knows who Alice is, remembers their history, and has a consistent personality across sessions. All on a Raspberry Pi 4 with no GPU.

## What Was Built (This Session)

### Phase 0: Smooth Servo Control
- `buddy/servo_controller.py` — Proportional + adaptive EMA (no PID/Kalman — SORT handles smoothing)
- Camera FOV mapping (62°/640px), gain=0.35, adaptive alpha (0.6→0.3→0.15)

### Phase 1: Person Detection + Body-Aware Head Estimation
- `buddy/detectors.py` — TFLite SSD MobileNet (~10 FPS) + Haar cascade on person ROI (every 3rd frame)
- HeadEstimator aims 30% above person bbox + 15° pitch bias for body tracking

### Phase 2: SORT Tracker
- `buddy/tracker.py` — Kalman filter per track + Hungarian assignment, persistent IDs

### Phase 3: Face Identification
- `buddy/face_id.py` — OpenCV SFace (128-dim embeddings), JSON database, async worker thread
- CLI enrollment with live preview, voice enrollment via "remember my face"

### Phase 4: Room Awareness + Companion Integration
- `buddy/room_awareness.py` — who's here, where last seen, LLM context summaries
- Room state injected into LLM instructions every 10s
- Personalized wake greetings

### Personality & Memory System
- `buddy/social_graph.py` — People database with roles, relationships, interests, notes
- `buddy/personality.py` — Fixed character traits + evolving mood + quirks
- `buddy/memory_compiler.py` — Compiles all sources into ≤500 word LLM context
- Session-end: LLM extracts new people/relationships from conversation → social graph
- Rich character prompt: 10 hand-written personality lines defining Nounou's soul

### Thread Architecture
- Detection thread (~10 FPS): capture → TFLite → SORT → face ID
- Servo thread (30 Hz): smooth head tracking from servo target
- Face ID worker (async): background face embedding + matching
- Voice thread: OpenAI Realtime API WebSocket

### Additional Features
- All 30 ActionFlow actions available to LLM
- Head pat wake from sleep (touch sensor polling)
- Volume set to 100% at startup
- Graceful Ctrl+C shutdown (first=save, second=force quit)
- Per-frame CSV logging with FPS overlay
- Voice commands: "who can you see?", "remember my face, I'm Alice"
- `--video` flag for companion (shows camera feed on HDMI)

### Key Bugs Fixed
- Sound direction disabled (ambient noise caused 110° servo jumps)
- CSI camera outputs BGR not RGB (removed cvtColor)
- Yaw limited to ±55° (CSI ribbon cable protection)
- Dual Kalman filter removed (SORT is single source of truth)
- PulseAudio device auto-detection (indices shift across reboots)
- Realtime API session.update needs `type: "realtime"` + dict not string

## Immediate Next Steps (Before Next Session)

### 1. Secure CSI Ribbon Cable
Physical fix — tape the cable down so head movement can't dislodge it. This has caused camera I/O errors 3+ times today.

### 2. Enroll Alice + Talia
```bash
QT_QPA_PLATFORM=xcb python3 -m buddy.face_id --enroll "Alice"
QT_QPA_PLATFORM=xcb python3 -m buddy.face_id --enroll "Talia"
python3 -c "
from buddy.social_graph import SocialGraph
g = SocialGraph()
g.update_person('Talia', role='friend', notes_add=[\"Alice's friend\"])
g.add_relationship('Alice', 'Talia', 'friend')
"
```

### 3. Alice's First Test
```bash
QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video
```
Watch. Take notes. Don't intervene. Her reactions ARE the roadmap.

## Future Work (Prioritized)

| Priority | Feature | Status |
|----------|---------|--------|
| Next session | Behavior Engine | Plan at `plans/Behavior_Engine_Plan.md` |
| Next session | Bluetooth speaker | Enables audio from the dog itself |
| Later | Episodic memory v2 | "Remember when..." conversations |
| Later | Adaptive volume | Adjust based on ambient noise |
| Later | Sound direction re-enable | Needs noise filtering + servo thread routing |
| Later | Wake-from-sleep voice fix | Realtime API may stop transcribing during sleep |

## Verification

1. `python3 -m buddy.face_id --list` — Alice, Dad, Talia enrolled
2. `python3 -c "from buddy.memory_compiler import MemoryCompiler; c = MemoryCompiler(); print(c.compile())"` — full personality + people + memory context
3. `QT_QPA_PLATFORM=xcb python3 -m buddy.companion --video` — everything works together
