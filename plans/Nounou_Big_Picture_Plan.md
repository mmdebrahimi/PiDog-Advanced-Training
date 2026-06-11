# Nounou: Big Picture Plan

> Complete roadmap from stationary companion to autonomous, memory-rich robot dog that follows Alice, maps her house, and remembers everything important.

---

## Current State (June 2026)

**Done:**
- Voice conversation (OpenAI Realtime API, sub-second latency)
- 30 physical actions available to LLM
- Person detection + tracking (YuNet + MOSSE + SORT, dead zone, parameter tuning)
- Face identification (SFace embeddings)
- Personality v3 (valence-arousal emotion, needs, jealousy, time-of-day, mood-driven actions)
- Behavior engine (GREET/TRACK/SEARCH/REST/SLEEP)
- Social graph + long-term memory + memory compiler
- Sleep/wake lifecycle + shutdown command
- BT speaker auto-detect + API cost monitoring
- Camera graceful degradation
- YuNet-first detection (TFLite fallback)

**Blocked on hardware:**
- Speaker (3.5mm or BT)
- Alice's first test

**Parallel track:**
- RL training package sent to laptop

---

## Layer Architecture

```
Layer 8: Full SLAM (Tier C)         ← LiDAR/depth cam + ROS 2 (future)
Layer 7: Visual Odometry (Tier B)   ← Pi 5 + heavier CV (future)
Layer 6: Room Nav + Home Base       ← needs walking + topological map
Layer 5: Topological Map (Tier A)   ← needs walking, visual place recognition
Layer 4: Follow Alice               ← needs walking + person tracking
Layer 3: Walking Locomotion          ← needs RL training (in progress)
Layer 2: Smart Arrivals + Memory v2  ← SOFTWARE ONLY (can start now)
Layer 1: Stationary Companion        ← DONE
```

---

## Family 1: Stationary Companion — DONE

Voice + tracking + personality + behavior engine. Complete.

---

## Family 2: Smart Arrival Behavior

**What:** Differentiate arrivals by identity. Alice gets excited greeting, known people get friendly greeting, strangers get curious introduction.

**Behaviors:**

| Trigger | Response |
|---------|----------|
| Alice arrives (not seen >5min) | Happy bark, excited wag, "Alice! I missed you!", high energy |
| Known person arrives | Greet by name, friendly but calmer, ask what they're up to |
| Unknown person arrives | Shy 3s → curious, ask name, offer to remember face |
| Alice leaves | Sad mood, look toward last known position |
| Everyone leaves >5min | REST, look toward door (fixed yaw), wait |

**Depends on:** Family 1 (done)
**Effort:** 2 sessions
**Status:** Can start now

---

## Family 3: Conversation Memory v2

**Problem:** Current memory is a flat markdown file of bullet-point facts, capped at 50 entries, updated by a single LLM summarization call at shutdown. This loses context, has no per-person separation, no conversation threading, and no way to ask "what did we talk about last time?"

### Memory Architecture

**Three-layer memory system:**

```
Layer 1: Soul (immutable)
  - Character traits, safety rules, name
  - Never changes
  - File: hardcoded in personality.py

Layer 2: Semantic Memory (long-term, per-person)
  - Facts about each person (interests, family, school, preferences)
  - Relationship graph
  - Milestones ("first time Alice said I love you", "learned Alice's birthday")
  - Compressed monthly by LLM digest
  - File: ~/.config/pidog/semantic_memory.json

Layer 3: Episodic Memory (session-level, rolling)
  - Last 5 session summaries per person
  - Each session: date, duration, topics, emotional tone, key moments
  - Enables "remember when we talked about...?" conversations
  - File: ~/.config/pidog/episodic_memory.json
```

### Semantic Memory Schema

```json
{
  "people": {
    "Alice": {
      "facts": [
        {"fact": "Alice is 7 years old", "learned": "2026-06-10", "confidence": "high", "source": "told-by-alice"},
        {"fact": "Alice's favourite colour is purple", "learned": "2026-06-12", "confidence": "high", "source": "told-by-alice"},
        {"fact": "Alice has a friend named Sara at school", "learned": "2026-06-15", "confidence": "medium", "source": "mentioned-in-conversation"}
      ],
      "milestones": [
        {"event": "First conversation", "date": "2026-06-10"},
        {"event": "Alice taught Nounou a new word", "date": "2026-06-14"}
      ],
      "topics_discussed": {
        "school": 12,
        "animals": 8,
        "drawing": 5,
        "space": 3
      }
    }
  }
}
```

### Episodic Memory Schema

```json
{
  "sessions": [
    {
      "date": "2026-06-12T16:30:00",
      "duration_minutes": 15,
      "people_present": ["Alice"],
      "summary": "Alice told Nounou about her school trip to the zoo. She loved the penguins. She asked Nounou if he could waddle like a penguin.",
      "emotional_tone": "happy, excited",
      "key_moments": [
        "Alice laughed when Nounou tried to waddle (twist body action)",
        "Alice said she wants to be a zookeeper when she grows up"
      ],
      "new_facts_learned": ["Alice went to the zoo", "Alice loves penguins", "Alice wants to be a zookeeper"]
    }
  ]
}
```

### How it works at runtime

**Session start:**
1. Load semantic memory for people who are present (from face ID)
2. Load last 3 episodic sessions for those people
3. Inject into LLM context: "Last time you talked to Alice, she told you about her school trip to the zoo. She loved the penguins."

**During session:**
- Track conversation topics in real-time (topic counter increments)
- Detect "key moments" (emotional spikes, new facts, laughter)

**Session end (shutdown):**
1. LLM summarizes the session → episodic entry
2. LLM extracts new facts → semantic entries (with date + source)
3. LLM extracts new people mentions → social graph updates
4. Cap episodic memory at 5 sessions per person (oldest dropped)
5. Monthly: LLM compresses old episodic entries into semantic facts

### Conversation callbacks for the LLM

New tools for the Realtime API:
- `remember_fact(person, fact)` — manually note something important mid-conversation
- `recall_fact(person, topic)` — search semantic memory for facts about a topic

### What this enables

- "Nounou, do you remember what I told you yesterday?" → "You told me about the zoo! You loved the penguins!"
- "What's my favourite colour?" → retrieves from semantic memory
- Proactive: "Last time you said you wanted to be a zookeeper. Do you still want to?"
- Per-person context: knows different things about different people
- Topic tracking: can say "We talk about animals a lot! You must really love them!"

**Depends on:** Family 1 (done)
**Effort:** 3 sessions
**Status:** Can start now

---

## Family 4: Walking Locomotion

**What:** Train PPO walking policy in MuJoCo, deploy to PiDog.

| Step | Where | Status |
|------|-------|--------|
| Validate reward function | Laptop | Package sent |
| Train PPO 3M steps | Laptop GPU | Waiting |
| Evaluate + render | Laptop | After training |
| Transfer to Pi | Email | After eval |
| Deploy on floor | Pi | After transfer |

**Depends on:** Laptop GPU availability
**Effort:** 2 sessions (1 laptop, 1 Pi deploy)
**Critical:** Dog MUST be on floor, not table

---

## Family 5: Follow Alice

**What:** Walk toward Alice when she's visible and moving. Stop when close.

| Component | Exists? |
|-----------|---------|
| Distance estimation (bbox size) | Yes — `bbox_to_distance_bin()` |
| Follow controller | Partial — `_follow_body()` exists |
| Speed control (proportional to distance) | No |
| Stop zone (face bbox >280px = close enough) | No |
| Lost target timeout (>10s stop, >30s SEARCH) | Yes — behavior engine |

**Depends on:** Family 4 (walking works)
**Effort:** 1 session

---

## Family 6: Topological Mapping (Tier A)

**What:** Learn places by visual signature. Not a geometric map — a graph of "this is the kitchen", "this is Alice's room", connected by transitions.

**How:**
1. MAP mode: user walks dog through house, names each room
2. At each stop: capture camera keyframes, extract ORB features or color histograms
3. Record place graph with connections
4. Store as `~/.config/pidog/house_map.json`

**At runtime:**
- Match current camera view to known places → "I'm in the kitchen"
- Track transitions → "I just moved from hallway to Alice's room"

**No GPS/LiDAR/depth camera needed.** Visual place recognition only.

**Depends on:** Family 5 (walking + following, so the dog can move between rooms)
**Effort:** 2 sessions

---

## Family 7: Room Navigation + Home Base

**What:** Nounou has a home (Alice's room), returns there when Alice is gone, watches the door.

| Behavior | Trigger | Response |
|----------|---------|----------|
| FOLLOW | Alice visible + moving | Walk toward her |
| RETURN_HOME | Alice gone >2min OR too far (tiny bbox >30s) | Navigate topological graph back to home place |
| DOOR_WATCH | At home + room empty | Point head at saved door yaw, limited sweep toward door |
| GREET_AT_DOOR | Person detected in door direction | Wake + identify + greet (Alice=excited, other=curious) |

**Navigation without SLAM:** Dead reckoning (track cumulative turns + steps, reverse them to go home). Simple but works for single-room return.

**Depends on:** Family 5 + Family 6
**Effort:** 2-3 sessions

---

## Family 8: Advanced Mapping (future, needs hardware)

**Tier B — Visual Odometry:** Track position via camera motion (ORB-SLAM3). Needs Pi 5.

**Tier C — Full SLAM:** Proper 2D map with metric distances. Needs LiDAR (RPLiDAR A1 ~$100) or depth camera (RealSense ~$200) + ROS 2.

**Defer until Families 5-7 work.**

---

## Dependency Graph

```
F1 Stationary Companion ─────── DONE
  │
  ├── F2 Smart Arrivals ──────── 2 sessions (NOW)
  │
  ├── F3 Memory v2 ──────────── 3 sessions (NOW)
  │
  └── F4 Walking ────────────── 2 sessions (laptop)
        │
        └── F5 Follow Alice ─── 1 session
              │
              ├── F6 Topo Map ── 2 sessions
              │     │
              │     └── F7 Room Nav ── 2-3 sessions
              │
              └── F8 SLAM (future)
```

**Parallel tracks:** F2, F3, F4 can all run simultaneously.
**Total to full vision:** ~13 sessions (some parallel).

---

## Priority Order (what to do next)

1. **Get speaker + test with Alice** (hardware, you)
2. **F2: Smart Arrivals** (software, 2 sessions — differentiates who arrives)
3. **F3: Memory v2** (software, 3 sessions — remembers everything)
4. **F4: Walking** (laptop training, parallel)
5. **F5: Follow Alice** (after F4)
6. **F6+F7: Mapping + Navigation** (after F5)

---

## Safety Rules (all families)

- **Table safety:** NEVER move the dog without asking the user first
- **Volume cap:** 80% max, ramped at startup
- **Three Laws:** Always in LLM system prompt
- **Safe mode:** On by default (no walking). Floor testing requires `--no-safe` + user confirmation
- **API cost:** Logged per session, warned >60 min
- **Child privacy:** No data leaves the Pi except OpenAI API calls. No cloud storage of face data or conversation logs.
