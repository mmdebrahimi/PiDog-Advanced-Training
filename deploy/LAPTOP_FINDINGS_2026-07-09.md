# Laptop findings — RL training tasks (LAPTOP_HANDOFF.md), 2026-07-09

> **RETRACTION (same day).** An earlier revision of this file claimed `pidog.xml` had a joint-axis
> defect making forward locomotion "kinematically impossible", and warned of a servo hard-stop
> hazard derived from that claim. **Both were WRONG.** `pidog.xml` is byte-identical to the model
> used by the known-good policy, which walks 432 mm. The axis claim and the hardware-safety
> warning derived from it are withdrawn in full. **Do not fix `pidog.xml`. Do not re-validate the
> servo mapping on account of this document.** What follows is the corrected finding.

**Bottom line: this repo's `main` contains a REGRESSED training stack. A walking policy already
exists and passes the MVP gate (432 mm). No model fix and no retraining-from-scratch is needed.**

---

## 1. The real defect: `main`'s `pidog_env.py` dropped the scripted base gait

The working training stack lives at `D:\pidog-Experiment\` (laptop). Compared to this repo's `main`:

| file | `D:\pidog-Experiment\` (works) | this repo `main` | |
|---|---|---|---|
| `pidog.xml` | `51f5291b71` | `51f5291b71` | **identical** |
| `sim_trot.py` | `dabc24ba77` | `dabc24ba77` | identical |
| `pidog_env.py` | **29-dim** obs, residual on scripted trot (+2 gait-clock `[sin,cos]`) | **27-dim** obs, direct joint targets, **no base gait** | **DIFFERENT** |
| `train.py` | has `checkpoints/` | **no checkpointing** | DIFFERENT |

The working env's own comment states the principle:

> *"The policy outputs a SMALL residual on top of a known-symmetric diagonal trot… Base gait is
> correct by construction… there is NO 'discover-a-gait' [problem]."*

`main`'s env asks PPO to **discover locomotion from scratch** with direct joint control. It cannot.
Verified across 8 configurations (~3.5 h CPU): every one converged to standing still (~15 mm) or to
a forward dive that falls by step ~35. Reward shaping, `ent_coef`, `gamma`, curriculum resume,
`--reset-std`, and a velocity-target reward all failed. That is the documented failure mode, not a
model bug.

**Proof the model is fine:** `eval_mvp.py pidog_policy_run15_STRAIGHT_TROT_MVP.zip` →
`mean_forward_mm=432 mean_lateral_mm=311 mean_steps=1000` → **MVP PASS**, on the byte-identical
`pidog.xml`.

### Recommended fix
Do **not** train against `main`'s `pidog_env.py`. Either port the 29-dim residual env + `train.py`
+ `eval_mvp.py` from `D:\pidog-Experiment\` into this repo, or train in that directory. `main`'s
27-dim direct-control env should be marked experimental or removed — it is a trap for the next
session, as it was for this one.

---

## 2. `train.py` (main) never checkpoints — real data-loss bug

`train.py:101` saves only *after* `model.learn()` returns. A 1,015,808-step run reached
`ep_rew_mean=527`, `ep_len_mean=1000`, and was interrupted before the save — the run was lost.
`D:\pidog-Experiment\` already has a `checkpoints/` dir, so this capability existed and was dropped.

`train_ckpt.py` (added on this branch) restores it: `CheckpointCallback` + `finally:`-save +
`--resume` + `--reset-std`. Useful independent of everything else.

## 3. `train.py:64` docstring prescribes `ent_coef=0.05`; the code passes `0.01`

**Do not "fix" the code to match the comment.** Measured: at `0.05` the policy std explodes to
**18.1** and the dog falls at step 40. The docstring is wrong for the current hyperparameters.

## 4. `LAPTOP_HANDOFF.md`'s success criteria are gameable

`ep_rew_mean > 500` **and** `ep_len_mean = 1000` are both satisfied by a policy that **stands
perfectly still** (measured: reward 586.86, ep_len 1000, forward **15.7 mm**). Only forward
distance catches it.

`eval_mvp.py` in `D:\pidog-Experiment\` already encodes the right bar and even names this failure:
`fwd>=200mm`, `steps>=800`, `fwd>|lateral|`, with the comment *"not standing ~16mm"*. **Use that
gate.** It should be ported to this repo alongside the env.

Note the handoff also states the scripted trot moves "~190 mm/cycle forward". Run standalone,
`sim_trot.py` measures **−74.4 mm** and falls over. It works as a *base gait inside the residual
env*, not as a standalone walker.

---

## 5. Runs (all 1.5M steps unless noted; all against `main`'s regressed env; none shippable)

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

All 8 are artifacts of the missing base gait. None indicates a model problem.

## 6. What this branch changes

Ported from `D:\pidog-Experiment\` (the working tree) into the repo root:

- `pidog_env.py` — **now the 29-dim residual env** (was 27-dim direct control)
- `train.py` — **now checkpoints** (`CheckpointCallback`), as the working tree always did
- `eval_mvp.py` — the correct, code-owned MVP gate. **Was missing from this repo.**
- `extract_weights.py`, `gait_diagnose.py`, `train_warmstart.py` — also missing; added

Quarantined / flagged:

- `experimental/pidog_env_direct_control.py` — the old 27-dim env, with a header recording the
  8-config negative result. Nothing imports it.
- `rl_training_package/pidog_env.py` (27-dim) and `sim/pidog_env.py` (24-dim) — also lack a base
  gait. **Flagged, not benchmarked** — I did not run them. Prefer the root env; gate any result
  from them with `eval_mvp.py`.

Removed: `train_ckpt.py` (redundant — the ported `train.py` checkpoints) and `pidog_fixed.xml`
(artifact of the retracted axis theory; stock `pidog.xml` is correct).

**Verification:** `eval_mvp.py <run15 policy> 5` run *in this repo tree* →
`mean_forward_mm=432 mean_lateral_mm=311 mean_steps=1000` → **MVP PASS** (exit 0).

## 7. Actual critical path (unchanged by any of this)

The physical dog still cannot hold a stand (LH hip servo). Until it stands, no policy deploys.
A walking policy already exists (`deploy/policy_straight_trot.npz`, run15/run18 lineage, 432 mm in
sim). The next real step is the hardware stand-fix via `deploy/stand_doctor.py` — operator-present,
Pi reachable — exactly as `WHEN_PI_IS_BACK.md` describes. Sim work is **not** on the critical path.

`SIM_TO_PIDOG_SERVO` / `SERVO_SIGN` remain `[unverified]` in their own comments — a pre-existing
condition the `--map-probe` step of the stand-doctor flow is designed to resolve on hardware. That
is worth doing on its own merits; it is **not** urgent because of this document.
