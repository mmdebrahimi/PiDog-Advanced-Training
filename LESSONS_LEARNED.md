# Lessons Learned

## Critical Bugs (cost us ~15 training runs)

### 1. MuJoCo ctrl expects RADIANS, not degrees
**The single biggest bug.** `data.ctrl` must be set in radians at runtime, even when `compiler angle="degree"` is in the XML. The `angle="degree"` setting only affects how XML *attributes* (like `range="-90 90"`) are parsed — it does NOT affect runtime `data.ctrl`.

We set `data.ctrl[:] = STAND_DEG` (degrees) for weeks. MuJoCo interpreted `ctrl=25` as 25 *radians* (1432°). Every joint slammed to its ±90° limit. The robot was a collapsed pile of limbs the entire time. The "standing height" of 50mm was just the torso sitting on the ground. The "266mm forward distance" was collapse momentum.

**How we found it:** Printed actual joint angles after settling — all at ±91° (joint limits) despite ctrl targeting 25-35°. Tested `np.radians(STAND_DEG)` and joints hit their targets exactly.

**Fix:** `data.ctrl[:] = np.radians(degrees_value)` everywhere.

### 2. STAND_DEG was all zeros
The environment initialized joints at `[0,0,0,0,0,0,0,0]` instead of the real PiDog standing pose `[25,35,-25,-35,35,35,-35,-35]` from `sim_trot.py`. With all joints at 0° the legs are straight, the robot is at an unstable height, and it collapses immediately.

**Fix:** Copy the STAND_DEG values from `sim_trot.py`.

### 3. Scripted trot gait was kinematically symmetric
The original 4-frame gait produced zero net displacement — every forward hip swing was cancelled by backward swings on other legs. The "266mm forward" was entirely from settling drift, not walking. We spent multiple sessions trying to BC from a gait that didn't work.

**How we found it:** Printed position after each gait cycle — identical values (0.266, -0.000, 0.051) across all 4 cycles.

**Fix:** Rewrote gait as proper 2-phase diagonal trot with asymmetric stance/swing.

## Debugging Methodology

### Print actual joint angles, not just ctrl targets
MuJoCo silently clamps values and can fail in non-obvious ways. Always verify:
```python
joints_actual = np.degrees(data.qpos[7:15])
print(f"Target: {STAND_DEG}, Actual: {joints_actual}")
```
If they don't match, the actuator can't reach the target (force limits, wrong units, etc.).

### Verify physics with sim_trot.py before training
The scripted trot is the ground truth. If `sim_trot.py --no-video` shows zero forward displacement, the env won't work either. Always validate the scripted gait produces real movement before running RL.

### Clear `__pycache__` after ANY edit to `pidog_env.py`
SubprocVecEnv spawns separate Python processes that load cached `.pyc` files. Stale cache means training uses old code while eval uses new code. We had a run where eval showed 1000-step episodes but training showed ep_len=1 — because eval ran in the main process (new code) while SubprocVecEnv workers loaded cached old code.

PowerShell: `Remove-Item -Recurse -Force __pycache__`

## Reward Engineering

### The "stand still" local optimum
With working actuators and alive bonus = +1.0, standing earns +1.0/step risk-free (1000 per episode). Walking at 0.05 m/s with forward_vel × 5.0 earns only ~1.25/step. The gap is too small — the policy finds standing first and std collapses before it discovers walking.

**Solutions tried:**
- Increasing forward_vel coefficient (2→5→20): didn't help alone
- Higher ent_coef (0.05): kept std alive but caused explosion to std=6.0
- Frame skip (15 steps per decision): reduced exploration space but episodes too short
- Standstill penalty (-0.5/step): made standing negative but combined poorly with frame_skip
- Velocity cap (0.15 m/s): prevented crash exploitation but limited reward signal

**What actually worked:** Simple config with working actuators. forward_vel × 5.0 + alive(1.0), no frame_skip, no standstill penalty. The radians fix changed the dynamics so fundamentally that the simple reward structure was sufficient. ep_len grew from 49→700 and reward from -31→+380.

### Don't tune rewards against broken physics
All our reward engineering (frame_skip, standstill penalty, velocity cap, ent_coef changes) was compensating for the radians bug. The actuators weren't working, so the robot couldn't move no matter what the reward said. Once the actuators worked, the simplest reward structure worked.

**Lesson:** Fix the physics first. Then tune rewards.

### Penalty weight guidelines (from our experiments)
| Penalty | Too low | Working range | Too high |
|---------|---------|--------------|----------|
| orientation | 2.0 (allows 30° tilt shuffle) | **5.0** | — |
| lateral_vel | 1.0 (allows diagonal drift) | **3.0** | — |
| smoothness | 0.05 (allows foot vibration) | **0.1** | 0.2 (blocks learning) |
| height | — | 3.0 | 5.0 (too punitive early) |
| termination | -10 (not enough) | -10 to -20 | -50 (still not enough to prevent crashes) |

### Termination thresholds: use for catastrophic failure only
Setting the tilt termination to 45° (quat_w < 0.7) killed the robot in ~12 steps — it couldn't learn anything. At 60° (quat_w < 0.5) it survives long enough to learn. **Use heavy penalties to shape behavior, use termination only for true catastrophe** (>60° tilt or <25mm height = definitely fallen).

### The "flail and crash" exploit
With high forward_vel reward and no cap, the robot learns to tip forward (gravity gives free velocity), earning a burst of reward before crashing. Solutions: cap forward velocity at walking speed (~0.15 m/s), or use a moderate termination penalty. But the best fix was just using working actuators — with proper control, random actions produce balanced movement, not crashes.

## Training Configuration

### What works for this robot
```python
# pidog_env.py
forward_vel_coeff = 5.0
alive_bonus = 1.0
orientation_penalty = 5.0    # force upright
lateral_penalty = 3.0        # prevent diagonal drift
smoothness_penalty = 0.1     # discourage vibration
height_penalty = 3.0
termination_penalty = -10.0
tilt_threshold = 60° (quat_w < 0.5)

# train.py
n_steps = 1024
batch_size = 256
learning_rate = 3e-4 (constant)
ent_coef = 0.01
network = 256-128 Tanh
```

### GPU on Windows
- Install CUDA PyTorch in the `.venv` (Python 3.10): `pip install torch --index-url https://download.pytorch.org/whl/cu126`
- Set `$env:CUDA_VISIBLE_DEVICES="0"` before running (fixes CUDA init error on Windows)
- Python 3.14 has no CUDA PyTorch builds — use 3.10-3.12

### Linear LR decay kills long runs
Linear decay from 3e-4→0 caused the policy to stop updating by 1.5M steps. Use constant LR for locomotion where training may need the full budget.

## Project Infrastructure

### Git
- Repository: https://github.com/mmdebrahimi/PiDog-Advanced-Training
- Claude skills repo: `C:\Users\b0652085\.claude\my_skills_repo` (remote: `https://github.com/OriginalGoku/my_skills.git`)

### Real PiDog hardware
- Bare aluminum/servo horn feet — no rubber pads. Don't add sphere contacts in simulation.
- Deploy trained policy to Pi at 192.168.2.26 via `scp pidog_policy.zip pidog@<PI_IP>:~/pidog_lab/sim/`
- Friction 0.8 is appropriate for carpet/rubber mat (where the real PiDog operates)

## Timeline of Discovery

1. **STAND_DEG = zeros** → robot collapses instantly → fixed by copying from sim_trot.py
2. **Height constants wrong** (0.12m vs actual 0.05m) → robot drops violently on reset → fixed by pre-setting joints + correct height target
3. **Reward too weak for walking** → robot stands still for 3M steps → tried many reward tweaks, none worked
4. **ctrl in degrees (THE BIG ONE)** → all joints at ±90° limits, robot was never actually standing → fixed with np.radians(), everything started working
5. **Gait kinematically symmetric** → scripted trot produces zero displacement → rewrote as 2-phase diagonal trot
6. **"Tilted shuffle" exploit** → robot leans 30° and vibrates feet sideways → increased orientation/lateral/smoothness penalties
7. **45° termination too aggressive** → robot dies in 12 steps, can't learn → reverted to 60°, let penalties do the shaping
