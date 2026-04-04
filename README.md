# PiDog Advanced Training

Train a quadruped robot to walk using reinforcement learning in MuJoCo simulation.

This project uses **PPO** (Proximal Policy Optimization) via [Stable Baselines3](https://stable-baselines3.readthedocs.io/) to teach an 8-DOF robot — modeled after the [SunFounder PiDog](https://www.sunfounder.com/products/pidog) — to walk forward while maintaining balance.

<p align="center">
  <img src="https://www.sunfounder.com/cdn/shop/files/PiDog.jpg" alt="PiDog Robot" width="300"/>
</p>

## Quick Start

```bash
# Clone the repo
git clone https://github.com/mmdebrahimi/PiDog-Advanced-Training.git
cd PiDog-Advanced-Training

# Create a virtual environment (Python 3.10 recommended for CUDA support)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# Install PyTorch with CUDA (GPU training)
pip install torch --index-url https://download.pytorch.org/whl/cu126

# Install remaining dependencies
pip install -r requirements.txt

# Verify the environment works
python pidog_env.py

# Train (3M steps, ~1 hour on GPU)
python train.py --timesteps=3000000

# Evaluate the trained policy
python train.py --eval

# Render a video
python train.py --render
```

> **Windows CUDA note:** If `torch.cuda.is_available()` returns `False` despite having an NVIDIA GPU, set `$env:CUDA_VISIBLE_DEVICES="0"` in PowerShell before running. This is handled automatically in `train.py`.

## Project Structure

```
PiDog-Advanced-Training/
|-- pidog.xml           MuJoCo robot model (4 legs x 2 joints, position servos)
|-- pidog_env.py        Gymnasium RL environment (obs, actions, reward, termination)
|-- train.py            PPO training, evaluation, and video rendering
|-- sim_trot.py         Scripted diagonal trot gait (baseline comparison)
|-- requirements.txt    Python dependencies
|-- DESKTOP_TRAINING.md Detailed setup and training guide
|-- LESSONS_LEARNED.md  Practical lessons from development
|-- TODOS.md            Backlog and future optimization ideas
```

## How It Works

### Robot Model

The robot has **4 legs with 2 joints each** (hip + knee), totaling 8 degrees of freedom. All joints use position-controlled servos (`kp=200`). The MuJoCo model mirrors the real PiDog's dimensions:

- **Torso:** 117mm x 98mm x 25mm, ~300g
- **Upper leg:** 42mm, **Lower leg:** 76mm
- **Standing height:** ~50mm (with bent-leg pose)

### Observation Space (27 dimensions)

| Component | Dims | Normalization |
|-----------|------|---------------|
| Joint positions | 8 | degrees / 45 |
| Joint velocities | 8 | rad/s / 10 |
| Torso quaternion | 4 | raw (w, x, y, z) |
| Torso linear velocity | 3 | raw (m/s) |
| Torso angular velocity (gyro) | 3 | raw (rad/s) |
| Torso height | 1 | meters / 0.05 |

### Action Space (8 dimensions)

Continuous actions in `[-1, 1]`, mapped to joint angle targets:

```
target = STAND_POSE + action * 15 degrees
```

An exponential smoothing filter (80% previous + 20% new) prevents jerky servo movement, which is important for sim-to-real transfer.

### Reward Function

The reward encourages forward locomotion while penalizing instability:

| Component | Weight | Purpose |
|-----------|--------|---------|
| Forward velocity | **+20.0** | Primary objective — walk forward |
| Alive bonus | +1.0 | Survive (0 if moving backward) |
| Energy | -0.05 | Penalize large actuator commands |
| Orientation tilt | -2.0 | Keep torso upright |
| Height deviation | -3.0 | Maintain ~50mm standing height |
| Lateral velocity | -1.0 | Minimize sideways drift |
| Vertical velocity | -1.0 | Minimize bouncing |
| Action smoothness | -0.05 | Penalize jerky movements |
| Termination | -10.0 | One-time penalty for falling |

### Training Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| Algorithm | PPO | Stable Baselines3 |
| Network | 256-128 MLP (Tanh) | Separate actor/critic |
| Parallel envs | 8 | SubprocVecEnv |
| Learning rate | 3e-4 (constant) | Linear decay caused premature convergence |
| Entropy coeff | 0.05 | High — prevents policy from collapsing to "stand still" |
| Rollout steps | 1024/env | 8192 total samples per update |
| Discount | 0.99 | |
| Control rate | 50 Hz | 10 substeps x 2ms timestep |

## Scripted Baseline

`sim_trot.py` implements a hand-coded diagonal trot gait for comparison:

```bash
python sim_trot.py              # Render video of scripted trot
python sim_trot.py --no-video   # Print stats only
```

The scripted gait achieves ~266mm forward distance over 4 cycles while maintaining stable posture.

## Deployment to Real Robot

After training, copy the policy to the Raspberry Pi:

```bash
scp pidog_policy.zip pidog@<PI_IP>:~/pidog_lab/sim/
```

## Key Lessons Learned

- **Standing pose matters:** The joint angles for standing (`[25, 35, -25, -35, 35, 35, -35, -35]` degrees) produce a ~50mm standing height, not the 120mm you might expect from straight legs. All height-related constants must use the actual standing height.
- **Clear `__pycache__` after editing the environment:** `SubprocVecEnv` spawns separate Python processes that load cached `.pyc` files. Stale cache = training uses old code while eval uses new code.
- **High entropy coefficient is critical:** Without `ent_coef=0.05`, the policy quickly learns to stand still (local optimum) and never discovers walking.
- **Forward velocity reward must be high:** At ~50mm/s walking speed, a 2x coefficient earns only +0.1/step — not enough to overcome stability penalties. 20x is needed.

## Dependencies

- Python 3.10+ (3.10 recommended for CUDA PyTorch)
- [MuJoCo](https://mujoco.org/) 3.1.6
- [Gymnasium](https://gymnasium.farama.org/)
- [Stable Baselines3](https://stable-baselines3.readthedocs.io/) 2.8+
- [PyTorch](https://pytorch.org/) 2.x (CUDA recommended)
- [mediapy](https://github.com/google/mediapy) + ffmpeg (for video rendering)

## License

This project is for educational and research purposes.
