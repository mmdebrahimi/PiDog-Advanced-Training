# Laptop → Pi handoff, 2026-10-30 (branch: laptop/oct-reconciliation)

For the Pi session. Pull this branch for review; do NOT merge to main without the user's
go-ahead (side-branch policy). Everything below was verified by running it on the laptop
(Python 3.12 venv, mujoco 3.1.6, SB3 2.9.2, torch CPU; 47 tests + 1 skip green).

## Corrections to the history you reconstructed from ~/pidog_lab/sim/

Your earlier account ("deploy.py never built; 24-dim obs with joint velocities; no actuator
model; RL track = 1M-step policy that never ran") came from the STALE `sim/` directory. The
repo's main has had the real stack since July:

1. **The deploy pipeline EXISTS**: `deploy/deploy_pidog.py` (50 Hz numpy loop), parity tests,
   `stand_doctor.py` (+38 tests), and SIX staged policies. Obs on hardware comes from the lib's
   commanded-angle cache — the no-encoder problem was already solved.
2. **The live env is the root 29-dim RESIDUAL env** (policy rides a scripted trot), not
   `sim/pidog_env.py` (24-dim) or `rl_training_package/` (27-dim). Both stale copies now carry
   LEGACY banners. The 8-config "PPO can't learn to walk" negative result applies only to the
   direct-control envs.
3. **Walking already works in sim**: re-verified on the laptop via the new `eval_npz.py` —
   straight_trot 461mm / dr_robust 351mm / fast_clean 496mm / smooth_trot 277mm, all MVP PASS.
   `policy_800k.npz` and `policy_trot29.npz` FAIL the gate (pre-residual) — never deploy them.
4. The July "axis-defect" claim was retracted same-day (`LAPTOP_FINDINGS_2026-07-09.md`):
   pidog.xml is correct; do not fix it.

## What this branch changes (5 commits)

- `eval_npz.py` — MVP gate for the .npz artifacts the robot actually runs.
- LEGACY banners on `sim/DESKTOP_TRAINING.md` + `rl_training_package/README.txt`;
  `deploy/BRANCH_AUDIT_2026-10.md` (all three old side branches: nothing stranded).
- `deploy_pidog.py`: servo map now LOADED from `joint_mapping.csv` (fail-closed), which
  carries your user-verified wiggle map (LH pins corrected 0<->1 swap); writes routed through
  the I2C-locked `legs_move` buffer; sign ownership pinned (lib's leg_directions is the single
  owner, deploy sends uninverted angles — runtime assertion against double-inversion);
  battery prompt; `--slew-cap` and `--stagger-ms` power guards.
- `deploy/power_audit.py` + tests — offline supply-load proxy of the exact deploy command
  stream. Result: every trot policy = 8 simultaneous servos, worst_sum 36-40 deg/tick;
  crawl reference = 4 simultaneous, 8.9. The trot sits in the known brownout regime.
- This file + the October update in `WHEN_PI_IS_BACK.md`.

## Pi-side sequence (unchanged shape, updated content)

1. Finish hardware verdicts: P3 swap test; back-left shin servo replacement = USER purchase
   decision (channel P0 confirmed good, so a servo swap fully fixes that leg).
2. Run the hw_checkup brownout step test (2→4→6 simultaneous, charged battery, user present).
   That number is the deploy gate: 8 safe → trot deploys as-is; <8 → tell the laptop session
   (robotics-b9) and the crawl-gait retrain fires (env change prepared, CPU training verified
   viable on the laptop).
3. Only then: `deploy_pidog.py --stand` (tethered) to verify the mapping/sign chain end-to-end,
   then `policy_dr_robust.npz` first (DR-trained, recommended for first hardware attempt),
   with `--slew-cap 2 --stagger-ms 5` on the first floor run.

## Known open items

- P3 (front-left shin) verdict pending the user's swap test.
- The sign-ownership chain (lib leg_directions vs csv) has its final confirmation only at the
  tethered `--stand` test — flagged in code comments.
- `stand_doctor.py` still targets the OLD LH-hip diagnosis in its prose; its probe/sweep modes
  are joint-agnostic and work for the shins unchanged. Not rewritten here to keep this branch
  reviewable.
