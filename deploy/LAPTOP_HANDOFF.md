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
