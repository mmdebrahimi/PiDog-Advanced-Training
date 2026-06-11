# Behavior Engine for PiDog

> Centralize Nounou's decision-making into a priority-based behavior engine that replaces scattered inline logic in companion.py's main loop.

---

## Problem Statement

Nounou's behavior logic was scattered across companion.py's main loop (~100 lines of inline state management), face_follower.py (sweep/track decisions), personality.py (idle ticks), and room_awareness.py (arrivals/departures). Adding new behaviors required editing the main loop directly, and there was no single place that answered "what should the dog be doing right now?" This led to conflicting actions (sweep fighting tracking) and made the system hard to extend.

## Design Decisions

### D1: Priority-based state machine, not LLM orchestrator

**Decision:** Use a simple priority lookup evaluated every tick, not an LLM call to decide behavior.

**Rationale:** An LLM call adds 500ms latency and API cost per decision. A priority lookup is instant and deterministic. The LLM handles conversation; the engine handles behavior selection.

**Trade-off:** Less flexible than LLM reasoning, but fast, predictable, and debuggable.

### D2: Engine sets mode, FaceFollower obeys

**Decision:** Added `set_behavior_mode()` to FaceFollower. Engine sets high-level mode ('track', 'idle', 'off'); FaceFollower adjusts its own sweep/servo behavior within that mode. Engine does NOT own servo control.

**Rationale:** FaceFollower already has a battle-tested 30 Hz servo thread with its own sweep/track/coast state machine. Inserting the engine between detection and servos would add latency and create two competing decision-makers for head motion. Instead, the engine acts as a coordinator.

**Trade-off:** Rejected extracting sweep logic from FaceFollower — less invasive, preserves existing servo loop.

### D3: RESPOND removed from priority list

**Decision:** Voice handling stays callback-driven via RealtimeVoice. No RESPOND behavior in the engine.

**Rationale:** Voice is asynchronous (Realtime API pushes audio events). The engine can't "decide" to respond. Including it would be misleading — either a no-op or a source of confusion about who owns voice state.

### D4: LED ownership contract

**Decision:** Engine owns ambient/behavior LEDs. Voice callbacks own transient LEDs (speaking=pink, thinking=yellow). `engine.restore_leds()` bridges them — called by `on_speaking_end` to return to behavior LEDs.

**Rationale:** LEDs were previously set in 4 places with no clear ownership. Without a contract, the engine's LED choices would be overwritten every time the dog speaks.

### D5: Start with 5 behaviors

**Decision:** GREET, TRACK, SEARCH, REST, SLEEP. No RESPOND.

**Rationale:** These 5 cover the core experience. Adding more only when needed avoids over-engineering.

## Implementation Plan

### Step 1: Add `set_behavior_mode()` to FaceFollower

**File:** `buddy/face_follower.py`

- Added `_behavior_mode` flag (default: `'track'`) and thread-safe `set_behavior_mode()` method
- Modified detection loop: sweep only triggers when `_behavior_mode == 'track'`
- Modified servo loop: skip all servo commands when `_behavior_mode == 'off'`
- Detection thread still runs in all modes (RoomState/SpatialMemory keep updating)

### Step 2: Add `set_leds()` to DogBehavior

**File:** `buddy/dog_behavior.py`

- Added `set_leds(mode, color, bps)` wrapper around `dog.rgb_strip.set_mode()`

### Step 3: Create BehaviorEngine

**File:** `buddy/behavior_engine.py` (new)

- `BehaviorEngine` class with priority-based `tick()` method
- Priority list (highest wins):
  1. SLEEP — `sleeping == True` → FaceFollower OFF, blue LEDs, poll touch
  2. GREET — person arrived <5s → wag tail, excitement spike, greeting context injection
  3. TRACK — person visible → FaceFollower TRACK, green LEDs, personality ticks, jealousy
  4. SEARCH — no one visible → FaceFollower TRACK (built-in sweep), blue LEDs
  5. REST — alone >10min → FaceFollower IDLE, doze off, dim white LEDs
- Sleep/wake lifecycle: `go_to_sleep()` and `wake_up(source)` with rituals
- LED management: `_set_leds(behavior)` and `restore_leds()` for voice callback bridge
- Room updates rate-limited to 2s (matches old behavior)
- Instruction updates rate-limited to 10s
- Personality ticks every 10s (spontaneous actions + jealousy)

### Step 4: Integrate into companion.py

**File:** `buddy/companion.py`

- Removed: `sleeping` flag, `wake_up()`, `on_sleep()`, arrival/departure hooks, stranger detection, instruction updates, idle ticks, jealousy checks, touch wake polling, `_SPONTANEOUS_ACTION_MAP`, all rate-limiting state (~100 lines removed)
- Added: `BehaviorEngine` init, `engine.tick()` in main loop, voice callbacks wired to engine
- Main loop reduced to ~10 lines
- `on_speaking_end` calls `engine.restore_leds()` instead of `dog.idle()`
- `on_sleep` wired directly to `engine.go_to_sleep`
- `on_touch_event` simplified (personality hook only, engine handles context injection)

## Verification

1. **Start companion:** `source ~/pidog_lab/.venv/bin/activate && python3 -m buddy.companion`
   - Engine prints transitions: `[Engine] TRACK -> SEARCH`
   - LEDs match behavior state

2. **Walk into room** -> GREET triggers (wag, greeting context injected)

3. **Stay visible** -> Transitions to TRACK (green LEDs, head follows)

4. **Leave room** -> After 3s: SEARCH (FaceFollower sweeps). After 10min: REST (doze off, dim LEDs)

5. **Say "goodnight"** -> SLEEP (lie down, blue LEDs, servos off)

6. **Pat head during sleep** -> `wake_up()`, stretch ritual, transitions to GREET or TRACK

7. **Ctrl+C** -> Graceful shutdown (unchanged)

8. **Video mode:** `python3 -m buddy.companion --video` — same behaviors + video overlay

9. **Regression check:** Face tracking smoothness unchanged (30 Hz servo thread untouched). Voice latency unchanged (callbacks not modified). Personality state persists across sessions.
