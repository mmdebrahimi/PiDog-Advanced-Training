# Behavior Engine for PiDog

> Centralize Nounou's decision-making into a priority-based behavior engine that orchestrates head tracking, actions, LEDs, and voice context based on all sensor inputs.

---

## Problem Statement

Nounou's behavior logic is scattered across modules — `face_follower.py` decides where to look, `companion.py` decides what to say, `room_awareness.py` tracks who's here, and they communicate via shared state and callbacks. There's no central "brain" that reasons about what the dog should be doing right now. This makes it hard to add new behaviors (greet on arrival, rest when alone, react to touch) and leads to conflicting actions (sound direction fighting servo thread, sweep fighting tracking).

## Design Decisions

### D1: Priority-based state machine, not LLM orchestrator

**Decision:** Use a simple priority lookup evaluated every 500ms, not an LLM call to decide behavior.

**Rationale:** An LLM call adds 500ms latency and API cost per decision. A priority lookup is instant and deterministic. The LLM handles conversation; the engine handles behavior selection.

**Trade-off:** Less flexible than LLM reasoning, but fast, predictable, and debuggable.

### D2: Behaviors as skill sequences, not agent frameworks

**Decision:** Each behavior is a sequence of direct commands (SetMood, Action, LookAt, LEDs, InjectContext), not an LLM agent.

**Rationale:** The 30 existing dog actions are already the skill layer. The engine just needs to know when to trigger them. No new abstraction framework needed.

### D3: Start with 5 behaviors

**Decision:** GREET, TRACK, SEARCH, REST, SLEEP. Add more only when Alice asks for them.

**Rationale:** Avoid over-engineering. These 5 cover the core experience.

## Implementation Plan

### Step 1: Create BehaviorEngine

File: `buddy/behavior_engine.py` (new, ~200 lines)

- `BehaviorEngine` class with 500ms tick
- Reads inputs: RoomState, TrackingState, VoiceState, PersonalityState, touch sensors, time of day
- Evaluates priority list, picks highest active behavior
- Each behavior controls: head target, body action, LED pattern, voice context injection, mood update

Behaviors (highest priority wins):
1. **GREET** — person just arrived (< 5s ago) → wag tail, look at them, excitement spike, inject greeting context
2. **TRACK** — person visible → follow with head servos
3. **RESPOND** — voice input detected → engage (existing voice handling)
4. **SEARCH** — no one visible for 3s → slow sweep
5. **REST** — no one for 10+ minutes → doze off, dim LEDs, low energy
6. **SLEEP** — commanded to sleep → lie down, blue LEDs, touch wake

### Step 2: Integrate into companion.py

File: `buddy/companion.py` (modify)

- Replace direct state management in main loop with `engine.tick()`
- Engine reads shared state, makes decisions, issues commands
- Voice callbacks still handle conversation; engine handles everything else
- Remove scattered behavior logic (sweep triggers, room print, instruction updates) — engine owns these

### Step 3: LED integration

File: `buddy/dog_behavior.py` (modify)

- Add `set_leds(mode, color, speed)` method wrapping `dog.rgb_strip.set_mode()`
- Behaviors set LED patterns: excited=rainbow, tracking=green pulse, searching=blue scan, rest=dim white, sleep=blue breath

## Verification

1. Start companion → engine prints current behavior state
2. Walk into room → GREET triggers (wag, greeting)
3. Stay visible → transitions to TRACK (smooth following)
4. Leave room → SEARCH after 3s (sweep), REST after 10min (doze off)
5. Say "goodnight" → SLEEP (lie down, blue LEDs, touch wake)
6. Pat head → GREET (wake up, excited)
