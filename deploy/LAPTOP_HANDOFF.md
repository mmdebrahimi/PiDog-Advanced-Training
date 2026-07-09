> ## ⚠ SUPERSEDED IN PART — read `LAPTOP_FINDINGS_2026-07-09.md` first
>
> **Tasks 1 & 2 (BC pretrain + PPO from scratch) are obsolete.** They targeted the repo's old
> 27-dim direct-control `pidog_env.py`, which cannot learn to walk: 8 PPO configurations
> (~3.5 h CPU) all converged to standing still (~15 mm) or a forward dive that falls by step ~35.
>
> The repo-root env is now the **29-dim residual env** (policy emits a small residual on a scripted
> symmetric trot), ported from `D:\pidog-Experiment\`. The old env is quarantined at
> `experimental/pidog_env_direct_control.py`. **A walking policy already exists and passes the gate**
> (`eval_mvp.py` on run15: `mean_forward_mm=432, mean_steps=1000` -> MVP PASS); see
> `deploy/policy_straight_trot.npz`. **No retraining from scratch is required.**
>
> Corrections to specific claims below:
> - "scripted trot ~190 mm/cycle forward" -- run standalone, `sim_trot.py` measures **-74.4 mm**
>   (backward) and falls over. It works only as a *base gait inside* the residual env.
> - "success: ep_rew_mean>500, ep_len_mean=1000" -- **gameable**: both are satisfied by a robot
>   standing perfectly still (reward 586.86, forward 15.7 mm). Use `eval_mvp.py` instead
>   (`fwd>=200mm`, `steps>=800`, `fwd>|lateral|`).
> - The laptop has **no CUDA** (torch CPU-only). MuJoCo is CPU-native; this is not a blocker.
> - `train.py` now checkpoints again (the version this handoff referenced did not, and a
>   1.0M-step run at `ep_rew_mean=527` was lost to an interruption).
>
> Task 3 (stand_doctor tests) stands: **37 passed / 1 skipped** (the skip is a Linux-only symlink
> test). The real critical path remains the physical stand-fix, not sim work.

---

# Laptop Handoff — RL Training Tasks

> Tasks that need GPU compute. Run on the laptop (Windows, CUDA, Python 3.10 .venv).

---

## Prerequisites

```powershell
cd PiDog-Advanced-Training
.venv\Scripts\activate
$env:CUDA_VISIBLE_DEVICES="0"
```

Verify CUDA: `python -c "import torch; print(torch.cuda.is_available())"`

## Task 1: BC Pretrain from Scripted Trot

The scripted trot (`sim_trot.py`) now produces ~190mm/cycle forward motion with a proper 2-phase diagonal gait. Use it to bootstrap the RL policy via behavioral cloning.

```powershell
# Clear cache first
Remove-Item -Recurse -Force __pycache__ -ErrorAction SilentlyContinue

# Run BC pretraining
python pretrain_bc.py
```

Expected: policy initialized near the scripted gait. Check that `pidog_bc_policy.zip` is created.

## Task 2: PPO Fine-tune from BC Policy

```powershell
python train.py --timesteps=3000000
```

Monitor TensorBoard: `tensorboard --logdir=ppo_pidog_tensorboard/`

**Success criteria:**
- `ep_rew_mean` > 500 by 1M steps
- `ep_len_mean` = 1000 (survives full episode)
- Forward displacement > 500mm per episode
- Lateral drift < forward / 3

## Task 3: Run stand_doctor tests

```powershell
python -m pytest deploy/test_stand_doctor.py -v
```

All 38 tests should pass. These test the safety-hardened calibration tool.

## Task 4: Evaluate + Render

```powershell
python train.py --eval     # Print stats
python train.py --render   # Save video
```

If training succeeds, the policy file (`pidog_policy.zip`) needs to be transferred to the Pi for deployment.

## Critical Bug Fixed This Session

**MuJoCo ctrl expects RADIANS, not degrees.** `data.ctrl` must be set in radians at runtime. The `angle="degree"` XML setting only affects how XML attributes are parsed, NOT runtime ctrl values. This was the single biggest bug — all prior training runs had joints slammed to limits.

Fix is already in `pidog_env.py`: `data.ctrl[:] = np.radians(degrees_value)`

## Transfer Back to Pi

```powershell
# Email the trained policy (Zscaler blocks direct Pi<->laptop)
# Or use a USB drive
```

Key file: `pidog_policy.zip` (the trained PPO model)
