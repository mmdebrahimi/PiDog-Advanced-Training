# Policy Training and Deployment

> Train PPO walking policy on corporate laptop via email transfer, deploy to real PiDog on the Pi.

---

## Problem Statement

The RL pipeline works end-to-end on the Pi (environment verified, 20k smoke test shows improvement), but full training (1M+ steps) needs a faster machine. The user's corporate laptop is powerful but can't connect to the Pi due to Zscaler. File transfer is via email.

## Design Decisions

### D1: Email-based file transfer

**Decision:** Email the 9.5KB training zip to the laptop, train there, email the ~200KB policy zip back.

**Rationale:** Corporate Zscaler blocks direct network access to the Pi. Email works for small files. The training package is self-contained (no Pi connection needed).

**Trade-off:** USB stick would also work but email is simpler for the user.

### D2: Train on laptop, deploy on Pi

**Decision:** All RL training on the laptop. Pi handles real robot control and policy inference only.

**Rationale:** Pi runs at ~50 FPS (7 hrs for 1M steps). Laptop runs at ~400+ FPS (30-40 min).

## Implementation Plan

### Step 1: Send training package (user action)
- Email `~/Desktop/pidog_training.zip` (9.5KB) to self
- Contains: `pidog.xml`, `pidog_env.py`, `train.py`, `sim_trot.py`, `requirements.txt`, `DESKTOP_TRAINING.md`

### Step 2: Train on laptop (user action)
- Unzip, install dependencies:
  ```bash
  pip install torch --index-url https://download.pytorch.org/whl/cpu
  pip install -r requirements.txt
  ```
- Verify: `python3 pidog_env.py` (should show "Survived 100 steps")
- Train: `python3 train.py --timesteps=1000000` (~30-40 min)
- Evaluate: `python3 train.py --eval` (expect mean reward >5, forward >200mm)
- Optional: `python3 train.py --render` (saves video of trained policy)
- Output: `pidog_policy.zip` (~200KB)

### Step 3: Transfer policy back (user action)
- Email `pidog_policy.zip` back to self
- Download on Pi to `~/pidog_lab/sim/pidog_policy.zip`

### Step 4: Build deployment script (Claude, on Pi)
- Create `~/pidog_lab/sim/deploy.py`
- Load trained PPO model (inference only, no MuJoCo needed at runtime)
- Read real robot state: IMU + joint angles → build 24-dim observation
- Run at 50Hz: observation → policy.predict() → action → `legs_move()`
- Log with `state_logger.py` for comparison
- Safety: terminate if IMU detects fall, limit joint velocity

### Step 5: Test on real robot
- Run `deploy.py` with robot lifted off ground first
- Verify servos move in a gait-like pattern
- Put robot on ground, observe walking behavior
- Compare real vs sim trajectories from logged data

### After deployment works
- System ID: tune MuJoCo params to reduce sim-to-real gap
- Retrain with tuned sim for better transfer
- Domain randomization for robustness

## Verification

1. Laptop training completes without errors, `pidog_policy.zip` produced
2. Eval on laptop: mean reward >5, forward distance >200mm per episode
3. `deploy.py` runs on Pi, servos produce gait pattern
4. Real PiDog attempts forward locomotion with trained policy
