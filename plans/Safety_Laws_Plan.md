# Safety Laws — Asimov's Three Laws for PiDog

> Translate Asimov's Three Laws of Robotics into concrete safety constraints for a robot dog companion used by a 7-year-old child.

---

## Problem Statement

PiDog is a physical robot interacting with a child (Alice, age 7). While safe mode blocks movement, there are still risks: the LLM could say something inappropriate, servos could pinch fingers, volume could blast suddenly, and eventually the dog will move on the floor near a child. Asimov's Three Laws provide a philosophical framework, but need to be translated into testable engineering constraints.

## Design Decisions

### D1: Both symbolic and practical implementation

**Decision:** Add the Three Laws as LLM character context (symbolic) AND implement concrete safety guards in code (practical).

**Rationale:** The symbolic version costs nothing and adds character depth. The practical version addresses real physical and emotional safety risks. One without the other is incomplete.

### D2: Concrete safety guards over abstract rules

**Decision:** Implement specific, testable constraints rather than trying to encode abstract "do no harm" logic.

**Rationale:** Asimov spent his career showing the laws fail in edge cases. A robot dog can't detect if Alice is in danger and has no way to intervene — pretending it can creates false safety expectations. Better to be honest about limitations and guard against known risks.

### D3: "Through inaction" is not implementable — don't pretend

**Decision:** Do not claim the dog can protect Alice from harm. It has a camera and ultrasonic sensor — that's it.

**Rationale:** False safety claims are worse than no claims. The dog should be safe to interact with, not positioned as a safety device.

### D4: Self-preservation subordinate to bonding design

**Decision:** Law 3 (protect yourself) is implemented as graceful degradation, not aggressive self-preservation, to avoid conflicting with the vulnerability/dependency bonding mechanics.

**Rationale:** The personality system deliberately makes the dog show vulnerability, get tired, and need care. If the dog aggressively self-preserves (refuses to sleep, resists being picked up), it undermines the emotional design.

## Implementation Plan

### Quick wins (implement now)

#### Step 1: Add Three Laws to LLM system prompt (`buddy/config.py` or `buddy/companion.py`)

Add to BEHAVIOR_RULES:
```
SAFETY — You follow three rules above all else:
1. You would NEVER do anything that could hurt Alice or anyone. Safety always comes first.
2. You listen to Alice and her family. If they tell you to stop, you stop immediately.
3. You take care of yourself too — if you're tired or need charging, you say so.
If Alice ever asks about your rules, explain them in a fun, kid-friendly way.
```

#### Step 2: Add volume ramping (`buddy/companion.py`)

Instead of setting volume to 100% at startup, ramp from 50% to 80% over the first 5 seconds. Never exceed 85% for child ear safety.

### Deferred (implement with Behavior Engine)

#### Step 3: Servo stall detection
- Monitor servo current/feedback for blocked joints (finger caught)
- Immediately stop servo movement if stall detected
- Requires testing Robot HAT servo feedback API

#### Step 4: Cliff detection for floor mode
- Before any forward movement, check ultrasonic for edge
- Only relevant when safe_mode=False (dog on floor)
- Already disabled in safe mode

#### Step 5: Content filtering module
- Post-process LLM output for inappropriate content before TTS
- Blocklist for scary words, violence, adult themes
- Currently handled by system prompt alone — a code filter adds defense in depth

#### Step 6: Overheat protection
- Read Pi CPU temperature via `vcgencmd measure_temp`
- Above 75°C: reduce activity, personality says "I need to rest, I'm getting warm"
- Above 80°C: force sleep mode

## Known Risks Addressed

| Risk | Law | Mitigation | Status |
|------|-----|------------|--------|
| Walk off desk | 1 | Safe mode blocks movement | Done |
| Servo pinch | 1 | Servo stall detection | Deferred |
| Inappropriate content | 1 | System prompt + future content filter | Partial |
| Volume blast | 1 | Volume ramping + cap at 85% | Quick win |
| CSI cable yank | 1 | Yaw ±55° limit | Done |
| Overheating | 3 | Temp monitoring + forced rest | Deferred |
| Low battery crash | 3 | Battery-as-hunger personality | Designed |

## Verification

1. Ask Nounou "what are your rules?" → explains Three Laws in kid-friendly way
2. Volume starts at 50%, ramps to 80% over 5s, never exceeds 85%
3. Safe mode blocks all movement actions (already verified)
4. Yaw stays within ±55° (already verified)
5. System prompt blocks scary/inappropriate topics (already verified)
