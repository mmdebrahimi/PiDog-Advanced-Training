# MuJoCo Simulation Pipeline for PiDog

> Build a MuJoCo model of PiDog, script a trot in sim, tune with system ID, then train locomotion with RL and deploy to real robot.

---

## Problem Statement

Phases 0-3, 5-6 are complete: hardware verified (12 servos, 5 sensors), 50Hz state logger built, basic gait runs on real robot. The next goal is to train locomotion policies in simulation and deploy them to the physical PiDog. MuJoCo was chosen over Isaac Sim as the simulation engine. SunFounder provided a 3D STEP assembly file for precise geometry.

## Design Decisions

### D1: MuJoCo over Isaac Sim

**Decision:** Use MuJoCo for physics simulation.

**Rationale:** MuJoCo is CPU-only (runs on Pi 4 and any laptop), has native Python API, built-in system ID tools, and is the standard in locomotion RL research. Isaac Sim requires an NVIDIA GPU with CUDA which the Pi 4 lacks.

### D2: Desktop for training, Pi for deployment

**Decision:** Develop MJCF model and train RL on desktop/laptop. Pi 4 runs real robot control and policy inference only.

**Rationale:** RL training needs millions of timesteps (30+ min on desktop, hours on Pi). MuJoCo viewer needs OpenGL (weak on Pi). Policy inference is cheap (small neural net forward pass).

### D3: Position actuators for servo modeling

**Decision:** Use MuJoCo `<position>` actuators with tuned `kp` to model hobby servos.

**Rationale:** Position actuators PID to a target angle — closest analog to real PWM servo behavior. The `kp` parameter maps to servo stiffness, `damping` to friction.

### D4: Defer ROS 2

**Decision:** Skip ROS 2 for now. MuJoCo has its own Python API and doesn't need ROS as middleware.

**Rationale:** ROS 2 was originally planned as Phase 7 before simulation. With MuJoCo's direct Python integration, ROS 2 is no longer a prerequisite. Learn it later when needed for real-time sim↔robot communication.

### D5: Dimensions from codebase + STEP file

**Decision:** Use dimensions already in `pidog.py` source code, supplemented by the SunFounder STEP file for verification.

**Rationale:** No calipers available. The codebase has body=117×98mm, legs=42mm+76mm, hip positions at ±49/±58.5mm. The STEP file (`~/Downloads/pidog-总体装配-2024-12-5.STEP`, 110MB) provides full 3D assembly for verification.

## Current State (what's done)

- MuJoCo 3.6.0 installed on Pi 4 (aarch64): `~/pidog_lab/.venv/`
- MJCF model created: `~/pidog_lab/sim/pidog.xml`
  - 8 position actuators, 440g total mass, correct body/leg geometry
  - Robot stands at zero angles (torso at 124mm)
  - Position actuators with kp=200
- Scripted trot runs: `~/pidog_lab/sim/sim_trot.py`
  - Robot moves ~200mm before toppling after 3 cycles
  - Heavy lateral drift due to joint sign convention mismatch
  - Video rendering works headless: `~/pidog_lab/sim/sim_trot.mp4`
- STEP file copied to: `~/pidog_lab/sim/pidog-总体装配-2024-12-5.STEP`

## Implementation Plan (remaining steps)

### Step 4: System ID — match sim to real
Files: `~/pidog_lab/sim/system_id.py` (new)

- Fix joint sign conventions (left/right mirroring) — compare real vs sim response to same commands
- On real robot: run `first_gait.py` with state logger → get joints + IMU CSV
- In sim: replay same joint commands → get sim joints + orientation
- Compare trajectories (joint tracking, pitch/roll, body height)
- Tune: `kp`, `damping`, `armature`, `mass` until sim ~80% matches real
- Key test: servo step response (command 0→45°, compare rise time)

### Step 5: Gymnasium RL environment
Files: `~/pidog_lab/sim/pidog_env.py` (new)

- Wrap MuJoCo model in Gymnasium env
- Observation: joint angles + velocities + torso quaternion + torso velocity (~31-dim)
- Action: 8 joint position targets for legs, normalized [-1, 1]
- Reward: forward velocity + alive bonus - energy penalty - orientation penalty
- 50Hz control (10 substeps at dt=0.002)
- Terminate if torso tilts >60° or height <20mm

### Step 6: Train basic locomotion with PPO
Files: `~/pidog_lab/sim/train.py` (new)

- stable-baselines3 PPO on desktop
- MlpPolicy (2×64 hidden layers)
- 1M timesteps (~30 min on laptop)
- Evaluate: save video of learned policy
- If unstable: add orientation penalty, curriculum

### Step 7: Deploy policy to real robot
Files: `~/pidog_lab/sim/deploy.py` (new)

- Load trained PPO model on Pi (inference only)
- Read IMU + joint state → observation → action → `legs_move()`
- 50Hz control loop with state logger recording
- Compare real vs sim behavior

## Key Resources

| Resource | Location |
|----------|----------|
| MuJoCo model | `~/pidog_lab/sim/pidog.xml` |
| Sim trot script | `~/pidog_lab/sim/sim_trot.py` |
| Real gait script | `~/pidog_lab/first_gait.py` |
| State logger | `~/pidog_lab/state_logger.py` |
| Joint mapping | `~/pidog_lab/joint_mapping.csv` |
| STEP 3D model | `~/pidog_lab/sim/pidog-总体装配-2024-12-5.STEP` |
| Gait log data | `~/pidog_lab/logs/` |

## Known Issues to Fix

1. **Joint sign conventions**: Left/right leg mirroring in MJCF doesn't match real PiDog's servo sign conventions. Causes lateral drift in sim.
2. **Stand pose mapping**: Real robot's STAND `[25,35,-25,-35,35,35,-35,-35]` creates a crouch; sim uses `[0,0,0,0,0,0,0,0]` (legs straight down). Need proper kinematic mapping.
3. **Mass estimation**: 440g is a guess. Real PiDog with battery may be 500-800g.
4. **Actuator kp**: Currently 200 — needs calibration against real servo step response.

## Verification

1. `pidog.xml` loads without errors, robot stands under gravity
2. Scripted trot produces visible walking (video) — **partially done, needs stability fix**
3. System ID: sim trajectories match real within ~20% for step responses
4. PPO training curve shows increasing reward over 1M steps
5. Deployed policy on real PiDog produces forward locomotion
