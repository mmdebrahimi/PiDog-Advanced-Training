# RL Reward Fix and Desktop Training

> Fix the broken reward function, package sim for desktop, train a walking policy on a faster machine.

---

## Problem Statement

The MuJoCo simulation pipeline works end-to-end (model loads, scripted gait walks 266mm, PPO trains and saves). But the 10k-step trained policy learned to fall forward in 3 steps rather than walk — the reward function incentivizes dying quickly over flailing. The alive bonus (1.0) is too weak relative to the orientation penalty (2.0) and energy penalty (0.001). Training on the Pi at 40 FPS is too slow for the iteration cycles needed to tune rewards (1M steps = ~7 hours). Training should happen on the desktop.

## Design Decisions

### D1: Fix reward before anything else

**Decision:** Fix the reward function as the immediate next step. Defer system ID, deployment script, and domain randomization until the policy walks in sim.

**Rationale:** System ID on a policy that falls in 3 steps is wasted work. The MJCF model physics are already proven (scripted gait works). The bottleneck is reward shaping, not simulation fidelity.

### D2: Train on desktop, deploy on Pi

**Decision:** Package `~/pidog_lab/sim/` for the desktop. All training happens there. Pi is for real robot control and policy inference only.

**Rationale:** 40 FPS on Pi vs ~400-800 FPS on a modern laptop. 1M steps: ~7 hours on Pi vs ~30 min on desktop.

### D3: Heavier alive bonus, termination penalty

**Decision:** Increase alive bonus, add termination penalty, reduce orientation/energy penalty weights.

**Rationale:** The agent currently prefers dying quickly (low cumulative penalty) over surviving longer (high cumulative penalty). A termination penalty of -10 plus stronger alive bonus flips this incentive.

## Implementation Plan

### Step 1: Fix reward function
File: `~/pidog_lab/sim/pidog_env.py`

Change `_compute_reward()`:
```python
reward = (
    2.0 * forward_vel          # strong forward incentive
    + 1.0                       # alive bonus per step
    - 0.0005 * energy           # gentle energy penalty (was 0.001)
    - 0.5 * orientation_penalty # gentle orientation penalty (was 2.0)
)
```

Add termination penalty in `step()`:
```python
if terminated:
    reward -= 10.0  # heavy penalty for falling
```

### Step 2: Package sim for desktop
Files: `~/pidog_lab/sim/requirements.txt` (new)

Create requirements.txt:
```
mujoco>=3.6
gymnasium>=1.2
stable-baselines3>=2.8
torch --index-url https://download.pytorch.org/whl/cpu
mediapy
```

Verify `sim/` directory is self-contained (no imports outside `sim/`).

### Step 3: Train on desktop (user action)
```bash
scp -r pi@192.168.2.26:~/pidog_lab/sim/ ./pidog_sim/
cd pidog_sim && pip install -r requirements.txt
python3 train.py --timesteps=1000000
python3 train.py --eval
python3 train.py --render
```

### Step 4: Evaluate and iterate
- If policy survives 500+ steps and moves forward: success, proceed to deployment
- If policy still falls: adjust reward weights, retrain
- Key metric: episode length (>100 steps = staying upright) and forward distance

### After policy walks in sim (future steps, deferred)
- Build `deploy.py` — load policy on Pi, run at 50Hz with `legs_move()`
- System ID — compare sim vs real trajectories, tune MuJoCo parameters
- Domain randomization — for robust sim-to-real transfer

## Verification

1. After reward fix: random policy episodes should last longer (>10 steps vs current 3)
2. After 1M steps training: policy survives 500+ steps without falling
3. Policy moves forward >100mm in 500-step evaluation
4. `train.py --render` produces video of walking robot
