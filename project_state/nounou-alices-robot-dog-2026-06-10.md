# Nounou: Alice's Robot Dog Companion
<!-- project-schema: 0.1 -->

> Initialized 2026-06-10. Project ID: nounou-alices-robot-dog-2026-06-10. Originating goal (verbatim user input): "Nounou: Alice's Robot Dog Companion".

## Project Context
- **Project ID:** nounou-alices-robot-dog-2026-06-10
- **Project root:** /home/pidog/pidog_lab
- **Captured:** 2026-06-10
- **Originating goal:** Nounou: Alice's Robot Dog Companion
- **Refined goal (if 3c produced one):** Build a robot dog companion for a 7-year-old named Alice on a SunFounder PiDog (Raspberry Pi 4) that recognizes her by face, follows her with its head, has natural voice conversations, expresses personality through physical actions and LEDs, remembers her across sessions, and eventually walks to her via RL-trained locomotion.
- **Horizon (months):** 12
- **Schema:** project-schema 0.1

## Empirical Concerns
- **Verdict:** N-A
- **Check status:** not-applicable
- **Provisional:** NO
- **Findings:** (no factual-shape claims in goal text; empirical check not applicable)

## Project vs Research-Program
- **Verdict:** PASS
- **Provisional:** NO
- **Classification:** project
- **Rationale:** Bounded scope (specific robot, specific user, specific capabilities), measurable success criteria (Alice engages daily), concrete platform (Pi 4 + SunFounder PiDog), finite timeline.

## Refinement Candidates
- **Verdict:** PASS
- **Provisional:** NO
- **Refined-from:** originating-goal
- **Candidates:**
  1. Alice has a sustained daily interaction with Nounou — companion experience works end-to-end: voice conversation, head tracking, face recognition, personality expression, BT speaker audio, sleep/wake lifecycle
  2. Nounou recognizes and greets Alice by name within 3 seconds of seeing her — face enrollment + behavior engine GREET trigger + voice context injection
  3. Nounou walks to Alice via RL-trained locomotion policy — MuJoCo training, sim-to-real transfer, deploy walking policy
  4. Alice asks to talk to Nounou again unprompted the next day — engagement metric driven by proactive conversation, daily rituals, emotional sounds, mini-games

## Goal Hierarchy
### Long-term (12+ months tier)
Nounou is Alice's daily companion — she talks to him, he recognizes her, follows her, expresses personality, remembers their history, and eventually walks to her.

### Mid-term (3-12 months)
| # | Milestone | Success Criterion | Horizon |
|---|---|---|---|
| 1 | Alice's first successful interaction | Alice engages >10 minutes and asks to play again | 1 month |
| 2 | Daily companion routine established | Alice interacts with Nounou on 5+ of 7 days for 2 weeks | 3 months |
| 3 | Companion features deepened based on feedback | Proactive conversation + emotional sounds + mini-games shipped | 4 months |
| 4 | RL walking policy trained and deployed | Nounou walks to Alice on voice command | 8 months |
| 5 | Full autonomous companion | Nounou operates independently: walks, talks, tracks, remembers, plays | 12 months |

### Short-term (≤1 month)
| # | Action | Class | Owner | Horizon |
|---|---|---|---|---|
| 1 | Reposition Pi board so CSI port faces head | ask-user | user | 1 day |
| 2 | Pair and configure Bluetooth speaker | ask-user | user | 1 day |
| 3 | Write BT audio auto-detection in companion.py | edit-local-code | claude | 1 day |
| 4 | Enroll Alice's face via voice command | ask-user | user | 1 day |
| 5 | Run first full interaction test with Alice | ask-user | user | 1 week |

## State Snapshot
### Assumptions
- Alice (age 7) will find a talking robot dog interesting enough to engage with (confidence: high)
- The CSI cable will stay connected after Pi board repositioning (confidence: medium)
- A Bluetooth speaker will provide sufficient audio quality for voice conversations (confidence: high)
- OpenAI Realtime API costs will stay manageable for daily use (confidence: medium)
- RL training on a laptop GPU will produce a walking policy within 3M steps (confidence: low)

### Evidence
| # | Claim | Source | Confidence | Captured |
|---|---|---|---|---|
| 1 | Voice conversation works with sub-second latency via Realtime API | tested 2026-04-05 | high | 2026-04-05 |
| 2 | Person detection + tracking works (TFLite + YuNet + SORT + MOSSE) | implemented 2026-06-10 | medium | 2026-06-10 |
| 3 | Personality system drives natural-feeling emotional responses | tested 2026-04-06 | high | 2026-04-06 |
| 4 | Behavior engine coordinates 5 behavior states correctly | implemented 2026-06-10 | medium | 2026-06-10 |
| 5 | MuJoCo simulation runs scripted trot successfully | tested 2026-04-03 | high | 2026-04-03 |
| 6 | CSI ribbon cable disconnects during head movement | observed 2026-06-10 | high | 2026-06-10 |
<!-- project-state:end:evidence -->

### Unknowns
- Will Alice sustain interest beyond the novelty period (week 2+)?
- Does the BT speaker audio quality match HDMI output?
- Can the YuNet + MOSSE tracking pipeline handle a moving child reliably?
- Will the RL reward function produce a stable walking gait?
- What features will Alice request that we haven't anticipated?

### Hypotheses (Active)
| ID | Statement | Status (open/under-investigation/falsified/confirmed) | Last-tested |
|---|---|---|---|
| H1 | Repositioning the Pi board will permanently fix the CSI cable issue | open | - |
| H2 | A scripted first encounter will produce a better first impression than unstructured play | open | - |
| H3 | Alice's reaction to the first test will identify the highest-value feature to build next | open | - |
| H4 | 3M PPO training steps on laptop GPU will produce a standing-then-walking policy | open | - |
<!-- project-state:end:hypotheses -->

### Decisions Made
| Decision | Date | Notes |
|---|---|---|
| Priority-based behavior engine over LLM orchestrator | 2026-06-10 | Deterministic, zero-latency, debuggable |
| YuNet over Haar for face detection | 2026-06-10 | Better at side/tilted faces from ground level |
| MOSSE inter-frame tracker for smooth servo updates | 2026-06-10 | 450+ FPS fills gaps between 10 FPS detections |
| Engine sets mode, FaceFollower obeys (no dual servo control) | 2026-06-10 | Clean separation of concerns |
| LED ownership: engine=ambient, voice=transient | 2026-06-10 | Eliminates 4-owner LED chaos |
| MuJoCo over Isaac Sim for simulation | 2026-04-02 | CPU-only, runs on Pi 4, better Python API |
| Alice's reaction IS the roadmap for Tier 2 features | 2026-06-10 | Don't build in a vacuum for a 7-year-old |
<!-- project-state:end:decisions-made -->

### Pending Decisions
| Decision | Proposer | Blocker | Notes |
|---|---|---|---|
| Which BT speaker to use | user | hardware purchase | Needs decent audio quality + portability |
| When to resume RL training on laptop | user | laptop availability | Parallel track, not blocking companion |
<!-- project-state:end:pending-decisions -->

## Bellman-Inspired Decision Frame

Per D5: surfaces the Bellman cognitive frame at the architecture level. v0.1 populates this at init; v0.2's `/project-step` reads from it to decide next actions. v0.1 does NOT iterate over the frame — it sets it up.

### Current state (one-line summary)
Companion system 85% complete (voice + tracking + personality + behavior engine); blocked on Pi board repositioning + BT speaker; RL track stalled on laptop GPU training.

### Target state / terminal condition
Alice has a sustained daily interaction with Nounou — she talks to him, he recognizes her, follows her smoothly, expresses personality, remembers their history, and eventually walks to her.

### Progress proxy
- **v0.1 metric:** `unknowns-retired` count + `gates-passed` count (raw counts, unweighted)
- **v0.2+:** weighted combination of unknowns-retired, gates-passed, evidence-confidence-improved, hypotheses-falsified (TBD via v0.2 design)

### Candidate next actions
| # | Action | Class | Expected progress | Expected info gain | Uncertainty | Cost |
|---|---|---|---|---|---|---|
| 1 | Reposition Pi board (CSI port faces head) | ask-user | high (unblocks camera) | medium (tests H1) | low | 30 min user time |
| 2 | Pair + configure BT speaker | ask-user | high (unblocks audio) | low | low | 1 hr user time |
| 3 | Write BT auto-detect code in companion.py | edit-local-code | medium | low | low | 30 min |
| 4 | Enroll Alice's face | ask-user | medium | medium (tests tracking) | low | 10 min |
| 5 | Run first interaction test with Alice | ask-user | high (milestone 1) | very high (tests H2, H3) | medium | 1 hr |
| 6 | Add proactive conversation initiation | edit-local-code | medium | medium | medium | 2 hrs |
| 7 | Add emotional sound layer (.wav files) | edit-local-code | medium | medium | low | 2 hrs |
| 8 | Validate RL reward function on laptop | run-tests | low | medium (tests H4) | medium | 1 hr |
| 9 | Run 3M step PPO training on laptop | run-tests | medium | high | high | 8+ hrs compute |
| 10 | Add API cost monitoring | edit-local-code | low | low | low | 30 min |
<!-- project-state:end:candidate-actions -->

### Re-evaluation trigger
- **Default:** re-run `/project-state` after any action class fires (auto-append to Action Log triggers stale-state check)
- **Manual override:** user invokes `/project-state <slug>` at any time
- **v0.2+:** automated trigger when N actions fire OR T days elapse OR a hypothesis falsifies (TBD)

## Allowed Action Classes (v0.2 placeholder — not enforced in v0.1)
- `propose` — auto
- `research` — auto (delegate to /research / /athena-research / /research-verify)
- `write-plan` — auto (delegate to /technical-plan / /save-plan)
- `edit-local-code` — REQUIRES per-action human approval
- `run-tests` — auto if local + sandboxed
- `ask-user` — auto
- `stop` — auto

## Action Log
| # | Date | Action class | Description | Outcome |
|---|---|---|---|---|
| 1 | 2026-06-10 | propose | /project-init invoked | ledger created |
| 2 | 2026-06-10 | edit-local-code | BT speaker auto-detect in companion.py | complete — detects bluez sink, falls back to HDMI |
| 3 | 2026-06-10 | edit-local-code | API cost monitoring — session duration logging on shutdown | complete — logs to ~/.config/pidog/usage.json, warns >60min |
| 4 | 2026-06-10 | edit-local-code | Restructure detection: YuNet full-frame first, TFLite person detect as fallback after 2s | complete — skips TFLite when face visible, ~2.5x more detection cycles |
| 5 | 2026-06-10 | edit-local-code | Smart Arrivals: identity-aware GREET (Alice=excited bark, family=warm, known=friendly, stranger=shy→curious→ask name) | complete |
| 6 | 2026-06-10 | edit-local-code | Door-watching REST: save_door_direction() + head points at door when alone | complete |
| 7 | 2026-06-10 | edit-local-code | Stranger greeting: unknown person triggers GREET with face enrollment prompt | complete |
| 8 | 2026-06-10 | edit-local-code | Memory v2 Step 1: SemanticMemory — per-person facts with dedup, milestones, topic counters | complete + tested |
| 9 | 2026-06-10 | edit-local-code | Memory v2 Step 2: EpisodicMemory — rolling session summaries with per-person filtering | complete + tested |
| 10 | 2026-06-10 | edit-local-code | Memory v2 Step 3: Combined shutdown extraction — single API call for facts + session + people + topics | complete |
| 11 | 2026-06-10 | edit-local-code | Memory v2 Step 4: MemoryCompiler — injects semantic + episodic context per visible person | complete |
| 12 | 2026-06-10 | edit-local-code | Memory v2 Step 5: companion.py wiring — init + shutdown + fallback to legacy | complete |
<!-- project-state:end:action-log -->

## Open Questions for User
- Which Bluetooth speaker will you use? (portability, battery life, audio quality matter for Alice's experience)
- When can you reposition the Pi board? (blocks all testing)
- When is a good time for Alice's first test? (weekend preferred — no school pressure)
