# PiDog RL Training — Diagnostics & Tuning Guide

A practical guide for reading training logs, identifying problems, and fixing them. Based on ~15 training runs and multiple debugging sessions.

---

## Reading the Training Logs

Every PPO iteration prints a block of metrics. Here's what to watch:

### The Big Three (check these first)

| Metric | What it means | Healthy range | Red flags |
|--------|--------------|---------------|-----------|
| `ep_len_mean` | Average episode length (steps) | Increasing toward 1000 | Stuck at 1-2 (instant death), stuck at 1000 too early (standing still) |
| `ep_rew_mean` | Average total reward per episode | Increasing over time | Stuck at a constant value, going negative |
| `std` | Policy's action standard deviation | 0.3–1.0 | < 0.1 (collapsed, no exploration), > 3.0 (exploding, random noise) |

### Secondary Metrics

| Metric | What it means | Healthy range | Red flags |
|--------|--------------|---------------|-----------|
| `explained_variance` | How well the value function predicts returns | > 0.5 | Near 0 (value function learning nothing), exactly 1.0 (trivial problem) |
| `clip_fraction` | % of policy updates clipped by PPO | 0.1–0.3 | > 0.5 (policy changing too fast), 0 (policy not changing at all) |
| `approx_kl` | KL divergence between old and new policy | 0.005–0.03 | > 0.1 (unstable updates), near 0 (no learning) |
| `learning_rate` | Current LR | 0.0003 (constant) | 0 or near 0 (if using linear decay — policy stops learning) |
| `fps` | Training speed | 200–900 | Sudden drop (computer sleeping, GPU throttling) |

---

## Common Problems and Solutions

### Problem 1: "Standing Still" (ep_len=1000, reward plateaued, std<0.1)

**Symptoms:**
- `ep_len_mean = 1000` from early on
- `ep_rew_mean` stuck at a fixed value (e.g., -564)
- `std` drops below 0.1 and keeps falling
- `clip_fraction` drops to 0

**Root cause:** The policy found that doing nothing (action≈0) earns a safe, consistent reward from the alive bonus. It stopped exploring before discovering that movement earns more.

**Diagnosis checklist:**
1. Is the alive bonus too high relative to forward velocity reward?
   - Standing earns `alive × 1000 steps`. Walking at speed `v` earns `(alive + vel_coeff × v) × steps`
   - The gap must be large enough to overcome exploration noise
2. Is `ent_coef` too low? Check if `std` collapsed early (< 100K steps)
3. Is the learning rate decaying to zero? (Use constant LR for locomotion)

**Fixes (try in order):**
1. Increase `forward_vel` coefficient (we use 5.0)
2. Increase `ent_coef` (0.01–0.05)
3. Use constant learning rate instead of linear decay
4. If all else fails: add a standstill penalty (-0.5 when velocity < threshold)

---

### Problem 2: "Flail and Crash" (ep_len=1-2, positive reward, std>3.0)

**Symptoms:**
- `ep_len_mean = 1–2` (dies almost instantly)
- `ep_rew_mean` is POSITIVE (e.g., +20)
- `std` explodes upward (3.0, 5.0, 6.0+)
- `entropy_loss` keeps increasing

**Root cause:** The robot discovered that tipping forward gives high forward velocity (gravity acceleration), earning a reward burst before crashing. The entropy bonus pushes std higher, making actions pure random noise.

**Diagnosis checklist:**
1. Is forward velocity uncapped? Crashing can produce 0.5+ m/s briefly
2. Is `ent_coef` too high? (> 0.03 can cause std explosion)
3. Is the termination penalty too low relative to crash reward?

**Fixes:**
1. Cap forward velocity: `min(max(forward_vel, 0), 0.15)`
2. Reduce `ent_coef` to 0.005–0.01
3. Increase termination penalty (-20 to -50)
4. The crash exploit mostly disappears when actuators work properly (radians fix)

---

### Problem 3: "Tilted Shuffle" (ep_len=700+, reward=380, moves diagonally)

**Symptoms:**
- Robot survives full episodes
- Moves forward but at a ~30° tilt
- Rapid foot vibration instead of clean steps
- Large lateral drift (lateral distance ≈ forward distance)

**Root cause:** The penalties for tilting, drifting, and vibrating are too weak relative to the forward velocity reward. The robot found that shuffling sideways while tilted is "good enough."

**Diagnosis — check the video:**
- Is the robot leaning to one side?
- Are the feet vibrating rapidly or making clean steps?
- Is the movement direction diagonal or straight?

**Fixes:**
1. Increase `orientation_penalty` coefficient (2.0 → 5.0)
2. Increase `lateral_penalty` coefficient (1.0 → 3.0)
3. Increase `smoothness_penalty` coefficient (0.05 → 0.1)
4. Do NOT tighten the termination threshold — let penalties shape behavior

---

### Problem 4: "Too Constrained" (ep_len=10-15, reward stuck at -45)

**Symptoms:**
- Very short episodes (10–15 steps)
- Negative reward plateaued
- `std` collapsing
- `explained_variance` high but nothing improves

**Root cause:** Penalties and termination thresholds are too strict. The robot can't survive long enough to learn anything useful.

**Diagnosis checklist:**
1. Did you recently tighten the tilt termination? (e.g., 60° → 45°)
2. Are multiple penalties all set to high values simultaneously?
3. Is the robot dying from a specific threshold (height or tilt)?

**Fixes:**
1. Revert termination threshold to 60° (`quat_w < 0.5`)
2. Reduce the most aggressive penalty by 50%
3. Rule: **use penalties for shaping, use termination only for catastrophe**

---

### Problem 5: "Actuators Not Working" (joints at ±90°, robot collapsed)

**Symptoms:**
- `ep_len_mean = 1000` but reward is strange
- Robot "stands" at ~12mm height (body on the ground)
- All joint angles at ±90° (limits) regardless of ctrl targets
- Forward distance = 266mm (settling drift, not walking)

**Root cause:** `data.ctrl` is being set in degrees instead of radians.

**Diagnosis — print actual joints:**
```python
joints = np.degrees(data.qpos[7:15])
print(f"Target: {STAND_DEG}, Actual: {joints}")
```
If actual ≈ ±90° while target is 25–35°, the ctrl is in wrong units.

**Fix:** `data.ctrl[:] = np.radians(degrees_value)` everywhere.

---

## Reward Balance Cheat Sheet

The reward per step for a standing robot should be LOWER than for a walking robot. Here's how to verify:

```
Standing reward/step = alive(1.0) - orientation(~0) - height(~0) - lateral(0) - vertical(0) - smoothness(0) - energy(0)
                     ≈ 1.0

Walking reward/step  = alive(1.0) + forward_vel × coeff - penalties_from_movement
                     must be > 1.0 for the robot to prefer walking
```

**Current working config:**
- Walking at 0.05 m/s: `1.0 + 5.0 × 0.05 - ~0.2 penalties ≈ 1.05`
- Standing: `1.0 - ~0.0 penalties ≈ 1.0`
- Gap: ~0.05/step × 1000 steps = 50 reward advantage for walking

This is a small gap, but sufficient when `std` stays healthy (0.3–0.8).

---

## Training Phases — What to Expect

A successful training run goes through roughly these phases:

### Phase 1: Random Exploration (0–100K steps)
- `ep_len` drops from 30–50 to ~10 as the robot tries wild actions and falls
- `ep_rew_mean` is very negative (-100 to -300)
- `std ≈ 1.0` (default initialization)
- `explained_variance ≈ 0` (value function hasn't learned yet)
- **This is normal.** The robot is exploring.

### Phase 2: Learning to Survive (100K–500K steps)
- `ep_len` starts climbing (10 → 50 → 100+)
- `ep_rew_mean` improves rapidly (-100 → -30 → 0)
- `std` decreases slowly (1.0 → 0.7)
- `explained_variance` jumps to 0.5–0.9
- **This is the critical learning phase.** If `ep_len` isn't increasing by 500K, something is wrong.

### Phase 3: Gait Refinement (500K–1.5M steps)
- `ep_len` reaches 1000 (full episodes)
- `ep_rew_mean` continues climbing (0 → 200 → 500+)
- `std` stabilizes at 0.3–0.6
- `explained_variance` stable at 0.8–0.95
- **The robot is walking.** Reward increases come from walking faster/straighter.

### Phase 4: Convergence (1.5M–3M steps)
- `ep_rew_mean` plateaus (slowly increasing or flat)
- `std` stable
- `clip_fraction` stable at 0.2–0.3
- **Training is done.** Further steps give diminishing returns.

### When to Kill a Run Early

Kill and restart if you see these at 500K+ steps:
- `ep_len_mean = 1000` with `std < 0.1` → standing still, won't improve
- `ep_len_mean = 1–2` with `std > 3.0` → flail-and-crash, won't improve
- `ep_rew_mean` hasn't changed in 200K+ steps → stuck in local optimum
- `clip_fraction = 0` → policy stopped updating entirely

---

## Pre-Flight Checklist (Before Every Training Run)

1. **Clear `__pycache__`**: `Remove-Item -Recurse -Force __pycache__`
2. **Set CUDA**: `$env:CUDA_VISIBLE_DEVICES="0"`
3. **Verify env**: `python pidog_env.py` — robot should stand at ~53mm, survive 100 steps
4. **Check ctrl units**: Print joints after reset — they should match STAND_DEG, NOT ±90°
5. **Activate .venv**: `.venv\Scripts\activate` (Python 3.10 with CUDA)

---

## Eval Interpretation

After training, run `python train.py --eval`:

| Metric | Good | Bad |
|--------|------|-----|
| steps = 1000 | Robot survives full episode | steps < 100 = falls frequently |
| forward > 500mm | Moving forward meaningfully | forward ≈ 30mm = just settling drift |
| lateral < forward/4 | Walking mostly straight | lateral ≈ forward = diagonal shuffle |
| reward > 0 | Net positive behavior | reward < 0 = penalties dominate |
| Consistent across episodes | Deterministic, learned behavior | High variance = unstable policy |

Always render a video (`python train.py --render`) and watch it. Numbers don't tell the full story — a robot can have good metrics but ugly gait (vibration, tilting), or modest metrics but clean walking.

---

## Quick Reference: Penalty Tuning

**If the robot tilts:** Increase `orientation_penalty` (current: 5.0)

**If the robot drifts sideways:** Increase `lateral_penalty` (current: 3.0)

**If the feet vibrate:** Increase `smoothness_penalty` (current: 0.1)

**If the robot bounces:** Increase `vertical_penalty` (current: 1.0)

**If the robot uses too much energy:** Increase `energy_penalty` (current: 0.05)

**If the robot doesn't move at all:** Decrease penalties, increase `forward_vel` coefficient

**If the robot dies too quickly:** Loosen termination thresholds (height, tilt)

**If the robot exploits tilting/crashing:** Tighten the relevant penalty, NOT the termination threshold
