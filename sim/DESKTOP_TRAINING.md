> [!WARNING] LEGACY DOCUMENT (superseded 2026-07-09; banner added 2026-10-30).
> The env this doc describes (sim/pidog_env.py, 24-dim) has NO scripted base gait and is NOT the
> training stack. The live stack is at repo ROOT: pidog_env.py (29-dim residual-on-trot),
> train.py (checkpointed), eval_mvp.py / eval_npz.py (the MVP gate), deploy/ (runs on the robot;
> deploy_pidog.py + staged policies + runbooks). A collaborating session read this file and
> reconstructed a false 'deploy was never built' history — hence this banner. See
> deploy/LAPTOP_FINDINGS_2026-07-09.md for the full reconciliation + axis-defect retraction.

# PiDog RL Training — Desktop Setup

## Quick Start

```bash
# 1. Install Python dependencies
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. Verify setup
python3 pidog_env.py

# 3. Train (1M steps, ~30-40 min on laptop)
python3 train.py --timesteps=1000000

# 4. Evaluate
python3 train.py --eval

# 5. Render video of trained policy
python3 train.py --render
```

## What's in this package

| File | Purpose |
|------|---------|
| `pidog.xml` | MuJoCo robot model (8 actuators, 4 legs x 2 joints) |
| `pidog_env.py` | Gymnasium RL environment |
| `train.py` | PPO training script (stable-baselines3) |
| `sim_trot.py` | Scripted trot for visual comparison |
| `requirements.txt` | Python dependencies |

## Training tips

- **1M steps** is a good starting point. If the robot walks but wobbly, try 3-5M.
- The saved model goes to `pidog_policy.zip` in this directory.
- To watch the scripted (non-RL) trot: `python3 sim_trot.py`
- To adjust reward weights, edit `_compute_reward()` in `pidog_env.py`.

## After training

Copy `pidog_policy.zip` back to the Pi:

```bash
scp pidog_policy.zip pidog@<PI_IP>:~/pidog_lab/sim/
```

Replace `<PI_IP>` with the Pi's IP (currently 192.168.2.26).

Then on the Pi, deploy to the real robot (deploy.py — to be built).

## Environment details

- **Observation (24-dim):** 8 joint angles + 8 joint velocities + 4 torso quaternion + 3 torso velocity + 1 torso height
- **Action (8-dim):** Joint position deltas from standing pose, range [-1, 1] mapped to ±30°
- **Reward:** 2x forward velocity + alive bonus - energy penalty - tilt penalty - 10 on termination
- **Control rate:** 50 Hz (10 sim substeps at dt=0.002)
- **Episode:** max 1000 steps (20 seconds), terminates if torso < 15mm or tilt > 60°