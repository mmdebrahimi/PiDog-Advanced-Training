# Laptop findings — RL training tasks (LAPTOP_HANDOFF.md), 2026-07-09

**Bottom line: Task 2 is not achievable as written. `pidog.xml` has a joint-axis defect that
makes forward locomotion kinematically impossible. Do NOT deploy any policy trained in this
sim to the physical robot.**

7 training configurations were run (~3.5 h CPU). All produced either a stand-still policy or a
forward dive. The hand-written scripted trot fails too. When every controller fails the same
way, the model is the problem — and it is.

---

## 1. THE MODEL BUG (blocking)

Two independent geometry signals say the body's **fore-aft axis is Y**:

| signal | value | implies |
|---|---|---|
| leg rectangle | front `lf/rf` at `y=-0.0585`, hind `lh/rh` at `y=+0.0585` (0.117 m) vs left/right at `x=±0.049` (0.098 m) | wheelbase > track width ⇒ fore-aft = **Y** |
| torso half-extents | `size="0.049 0.0585 0.0125"` → 0.098 x by 0.117 y | long axis = **Y** |

But **all 8 hip/knee joints hinge about Y** (`axis="0 1 0"` / `"0 -1 0"`), so every leg swings in
the **x–z plane** — perpendicular to the body's fore-aft axis. Measured directly:

```
pidog.xml        hip swing -> dx=-0.0164 dy=+0.0000   (legs swing LATERALLY)
pidog_fixed.xml  hip swing -> dx=+0.0000 dy=+0.0164   (legs swing FORE-AFT)
```

**The legs can only push sideways. No reward function, entropy value, discount factor, or
curriculum can make this robot walk forward.** That is why 7 controllers all failed.

On the real PiDog the hip servo swings the thigh fore-aft, so the hinge must be about the
**lateral** axis. `pidog_fixed.xml` (in this worktree, uncommitted) rotates all 8 hinges to
`axis="±1 0 0"` and is verified correct at the kinematic level.

### What is NOT yet established

- **The fix is not complete.** With corrected axes the scripted trot *still falls over*
  (`Still standing: NO`). Both models fall, so the displacement numbers from `sim_trot.py`
  in both cases are contaminated by tumbling and prove nothing about gait quality.
- Rotating the axes **changes the standing pose**: torso height at stand goes 0.0543 → 0.0607 m.
  `STAND_DEG` is expressed about the old swing plane and must be **re-derived**.

### ⚠ Hardware-safety implication — read before any deploy

`deploy_pidog.py`'s `SIM_TO_PIDOG_SERVO` / `SERVO_SIGN` are premised on the current (wrong) axis
convention, and both are already marked `[unverified]` in their own comments. A policy trained
under a corrected axis convention, pushed through a mapping built for the old one, **commands the
real servos in the wrong plane — into hard-stops.** That is the gear-strip failure mode. Fixing
the sim axes therefore requires re-validating the servo mapping on hardware, operator-present,
before any policy runs on the dog.

---

## 2. `train.py` never checkpoints (data-loss bug)

`train.py:101` calls `model.save()` only *after* `model.learn()` returns. A 1,015,808-step run
reached `ep_rew_mean=527`, `ep_len_mean=1000` and was interrupted before the save — **the entire
trained policy was lost.** Any interruption destroys the whole run.

Fixed here in `train_ckpt.py`: `CheckpointCallback` (every 50k) + a `finally:` save + `--resume`.
Recommend porting this to `train.py`.

## 3. `train.py:64` docstring prescribes `ent_coef=0.05`; the code passes `0.01`

**Do not "fix" the code to match the comment.** Measured: at `0.05` the policy std explodes to
**18.1** and the dog falls at step 40. The docstring is wrong for the current hyperparameters.

## 4. The success criteria in LAPTOP_HANDOFF.md are gameable

`ep_rew_mean > 500` **and** `ep_len_mean = 1000` are both satisfied by a policy that **stands
perfectly still** (measured: reward 586.86, ep_len 1000, forward **15.7 mm**). Only the
forward-distance criterion catches it. Reward alone must never be the ship signal.

Also: the handoff states the scripted trot moves "~190 mm/cycle forward". Measured on the
unmodified model: **−74.4 mm (backward), −122.3 mm lateral, falls over.**

---

## 5. Runs (all 1.5M steps unless noted; none shippable)

| # | config | ep_len | forward | outcome |
|---|---|---|---|---|
| 1 | baseline (fwd=5, alive=1.0, γ=0.99, ent=0.01) | 1000 | 15.7 mm | stands still |
| 2 | ent_coef 0.05 | 40 | 7.8 mm | std→18.1, flails, falls |
| 3 | fwd=20, alive=0.5 | 33 | 86 mm | dives forward, falls |
| 4 | fwd=20, alive=1.0 | 34 | 118 mm | dives, falls |
| 5 | γ=0.995, term=−50, fwd=20 | 39 | 103 mm | dives, falls |
| 6 | curriculum resume + fwd=10 (1M) | 1000 | 14.8 mm | balance kept, never explores |
| 7 | + `--reset-std 0.6`, ent=0.02 | 1000 | 14.7 mm | explores upright, re-collapses |
| 8 | velocity-target reward `exp(-(v-0.15)²/0.1²)` | 1000 | 14.6 mm | plateaus exactly at standing value |

Run 8 is the telling one: walking paid 3.0/step vs standing 0.316/step, and PPO *still* chose
standing — because a forward gait is not reachable in this model at all.

---

## 6. Artifacts (laptop, `D:\pdtrain\`, uncommitted unless noted)

- `train_ckpt.py` — checkpointed trainer (`--resume`, `--reset-std`, `--gamma`, `--ent-coef`)
- `pidog_env.py` — reward made env-var tunable; **defaults reproduce canonical behavior exactly**
  (`PIDOG_REWARD_MODE`, `PIDOG_FORWARD_WEIGHT`, `PIDOG_ALIVE_BONUS`, `PIDOG_TERM_PENALTY`,
  `PIDOG_VEL_TARGET|SIGMA|WEIGHT`)
- `pidog_fixed.xml` — axis-corrected model, kinematically verified, **stand pose not re-derived**
- `pidog_policy*.zip`, `checkpoints/` — trained policies. **All are stand-still or diving. None walk.**

## 7. Recommended next step (needs a human decision)

Fixing the model is a real piece of work, not a tuning pass: correct the 8 hinge axes, re-derive
`STAND_DEG` for the new swing plane, re-validate `SIM_TO_PIDOG_SERVO`/`SERVO_SIGN` against the
physical robot (operator-present, gear-strip risk), then retrain. It also invalidates every
policy trained to date.

Until that is done, `policy_straight_trot.npz` (run18, "466 mm") and every artifact in this repo
that claims forward motion should be treated as **suspect** — they were produced under the same
model. Worth checking whether run18's 466 mm was measured along x or y.
