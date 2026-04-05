# Person Finding Strategy for PiDog

> Layered approach to find and track a person from ground level: sound direction → head snap + tilt up → face detection → sweep fallback.

---

## Problem Statement

The PiDog sits ~10cm off the ground. A 7-year-old's face is ~100cm up. The camera's default angle sees floor/furniture, not faces. The dog needs to orient toward the person before face detection can work. The sound direction sensor (TR16F064B, 360°, 20° resolution) is already on the PiDog and working — it's the natural way to find someone who's talking to the dog.

## Design Decisions

### D1: Sound direction as primary person-finding signal

**Decision:** When no face is detected, use the sound direction sensor to snap the head toward the voice source and tilt up.

**Rationale:** Voice is the natural trigger — Alice talks to the dog, the dog turns toward her voice. The sensor gives a rough heading (±20°) which is enough for the camera's FOV (~60°) to find the face. Instant orientation vs 5-10s sweep.

**Trade-off:** Only works when the person is talking. Silent person = can't find them. Mitigated by face sweep as fallback.

### D2: Default head pitch tilted up

**Decision:** Default idle head pitch to +20° (looking slightly upward) instead of 0° (horizontal).

**Rationale:** Humans are above the dog. Looking up by default increases the chance of catching a face even without sound direction. The pitch servo range goes to +30°.

### D3: Layered search strategy

**Decision:** Five layers, in priority order:

1. **Default:** Head tilted up 20°
2. **Voice detected:** Sound direction → snap head yaw toward source → pitch up
3. **Face detected:** Proportional head tracking (already built in face_follower.py)
4. **No face after 3s:** Slow yaw sweep left-right while tilted up
5. **Face lost:** Return to last known direction, wait 2s, then sweep

**Rationale:** Mimics real dog behavior — hears something, turns toward it, finds the person, tracks them. If no sound, looks around searching.

## Implementation Plan

### Step 1: Add sound-directed search to face_follower.py
File: `~/pidog_lab/buddy/face_follower.py`

In `_tracking_loop()`, when no face is detected:
- Check `dog.dog.ears.isdetected()` and `dog.dog.ears.read()`
- Convert 360° direction to yaw: 0-180° → negative yaw (right), 180-360° → positive yaw (left)
- Clamp to ±80°
- Set pitch to +20° (look up at human)
- Move head toward sound source

### Step 2: Add default upward tilt
File: `~/pidog_lab/buddy/face_follower.py`

Change initial `self.pitch = 0` to `self.pitch = 20` so the dog starts looking up.
In `center_head()`, set pitch to 20 instead of 0.

### Step 3: Add slow sweep fallback
File: `~/pidog_lab/buddy/face_follower.py`

When no face detected AND no sound detected for 3+ seconds:
- Sweep yaw slowly between -60° and +60° at ~10°/second
- Keep pitch at +20° (looking up)
- If face found during sweep, stop and track

### Step 4: Integrate with companion.py
File: `~/pidog_lab/buddy/companion.py`

- Start face follower alongside voice session
- During conversation: head-only tracking (face_follower tracks while voice plays)
- Sound direction feeds into face follower automatically (same Pidog instance)

## Verification

1. Start face_follower standalone, speak from the side → dog head snaps toward voice
2. Move face around → dog head tracks face smoothly
3. Step out of view → dog sweeps searching after 3 seconds
4. Speak again from new position → dog snaps back toward voice
5. Default idle pose: head tilted slightly up, not horizontal
