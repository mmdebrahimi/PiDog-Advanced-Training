# Personality Soul Upgrade — Nounou's Inner Life v3

> Add needs system, continuous emotion decay, vulnerability, care rituals, and spontaneous behaviors to make Nounou feel alive and trigger child bonding — inspired by Aibo, Cozmo, Lovot, and Moflin research.

---

## Problem Statement

Nounou's personality was shallow — mood only changed at session boundaries and when the owner arrived. The dog never got bored, never showed fear, never sought attention, and never missed Alice when she left. Research on commercial robot pets (Aibo, Cozmo, Lovot, Moflin) and academic affective computing papers shows that **dependency/neediness**, **vulnerability**, and **care rituals** are the top 3 mechanisms that make children bond with robot pets. Touch sensor events and person departures existed as inputs but didn't feed into the personality system.

A bug was also discovered: `companion.py:299` computed arrival diffs *after* updating `last_who_printed`, so `on_person_seen()` never fired.

## Design Decisions

### D1: Valence-Arousal emotion model with lazy exponential decay

**Decision:** Replace discrete mood states with a continuous 2D valence-arousal model. Decay toward personality baseline using exponential decay (half-life ~140s). Compute lazily — only when mood is queried.

**Rationale:** VAD is the standard in affective computing (used by Moflin, academic research). Lazy evaluation means zero CPU cost when not queried. The companion loop queries every 2s, giving smooth emotional transitions.

**Trade-off:** More complex than discrete states, but the mood label is still derived for backward compatibility.

### D2: Three needs — attention, stimulation, rest

**Decision:** Start with three needs that drift upward over time (~0.01/min) and are satisfied by specific interactions (petting, talking, sleeping).

**Rationale:** Maps directly to the highest-impact bonding mechanisms: dependency (attention), autonomy/surprise (stimulation), and care rituals (rest). Three is enough to drive varied behavior without over-engineering.

### D3: All spontaneous behaviors map to existing ActionFlow actions

**Decision:** No new servo animations. Personality suggestions map to existing actions: whimper→howling, yawn→doze off, confused→think, etc.

**Rationale:** ActionFlow already has 30 actions covering the full expression range. Adding new animations requires servo choreography and testing. The personality upgrade is about *when* to trigger actions, not *what* actions exist.

### D4: Jealousy capped at 2 per session with 60s cooldown

**Decision:** Subtle jealousy (one action + LLM context injection) only triggers when owner is present with others, attention need > 0.5, and max 2 times per session.

**Rationale:** Jealousy is charming in small doses but annoying if overdone. Lovot does this successfully. The hard cap prevents it from becoming a negative experience.

### D5: Personality owns all state, no new modules

**Decision:** Extend `personality.py` rather than creating a separate emotions or needs module.

**Rationale:** The needs system is personality state — it belongs in the same JSON blob and class. Fragmenting the "soul" across files would complicate the 500-word context budget and the memory compiler integration.

## Implementation Plan

### Step 1: Extend personality state schema (`buddy/personality.py`)
- Added `emotion` (valence, arousal, last_update) and `needs` (attention, stimulation, rest) to `_DEFAULT_STATE`
- Added v2→v3 migration in `_load()`, seeding emotion from existing mood values
- Added `vulnerability` and `jealousy_count` fields

### Step 2: Implement lazy emotion decay (`buddy/personality.py`)
- `_apply_decay()` called at top of every read/event method
- Exponential decay: `v = baseline + (v - baseline) * exp(-λ * dt)`, λ=0.005
- Needs drift upward linearly (~0.01/min attention/stimulation, ~0.005/min rest)
- `_update_mood_label()` derives discrete label from VA coordinates
- Saves only if delta > 0.01 to avoid disk thrash, debounced to 2s minimum

### Step 3: Add event hooks (`buddy/personality.py`)
- `on_touch(style)` — gentle: valence+0.15, attention-0.3; rough: valence-0.05, arousal+0.2
- `on_person_departed(name, role)` — owner: valence-0.2, attention+0.3; stranger: valence+0.05
- `on_stranger_seen()` — arousal+0.15, valence-0.05, sets vulnerability="shy"
- `on_interaction()` — attention-0.15, stimulation-0.05
- `on_idle_tick()` — applies decay, returns action suggestions based on needs thresholds + 2% random vulnerability
- `on_jealousy_check()` — returns context string for LLM injection when conditions met

### Step 4: Upgrade prompt builder (`buddy/personality.py`)
- Conditional needs/vulnerability/energy sections added to `get_personality_prompt()`
- Adds ~15-30 words per active section, ~80 words worst case, within 500-word budget

### Step 5: Wire touch sensor → personality (`buddy/dog_behavior.py` + `buddy/companion.py`)
- Added `_touch_callback` field and `on_touch(callback)` method to `DogBehavior`
- `_poll_sensors()` calls callback after existing action triggers
- `companion.py` registers callback that updates personality + LLM instructions

### Step 6: Fix arrival bug + wire departures (`buddy/companion.py`)
- Moved arrival/departure diff computation *before* `last_who_printed` update
- Added `on_person_departed()` hook for each departed person
- Added stranger detection from room summary

### Step 7: Add idle tick + spontaneous behaviors (`buddy/companion.py`)
- 10s `PERSONALITY_TICK_INTERVAL` in main loop
- Maps personality suggestions to ActionFlow actions via `_SPONTANEOUS_ACTION_MAP`
- Jealousy check runs alongside idle tick

### Step 8: Enhanced care rituals (`buddy/companion.py`)
- Goodnight: `on_session_end()` → stretch → doze off → lie → blue breath LEDs
- Wake-up: `on_session_start()` → stretch → shake head → sit → idle

## Verification

1. Start companion → personality prints initial mood with needs at 0
2. Wait 3+ minutes idle → `on_idle_tick()` returns attention-seeking → dog whimpers
3. Pet the dog (touch sensor) → mood boosts, attention need drops
4. Alice arrives (face recognized) → `on_person_seen` fires (bug fixed), excitement spikes
5. Alice leaves frame for 60s → `on_person_departed` fires, valence drops
6. Unknown person appears → `on_stranger_seen` fires, shy behavior
7. Alice + Talia in room, attention > 0.5 → subtle jealousy (max 2/session)
8. Say "goodnight" → enhanced sleep ritual (stretch → doze → lie → blue LEDs)
9. Pat head to wake → enhanced wake ritual (stretch → shake → sit)
10. `get_personality_prompt()` includes needs/vulnerability lines when active
