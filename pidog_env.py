#!/usr/bin/env python3
"""Gymnasium environment for PiDog quadruped locomotion in MuJoCo.

Trains an 8-DOF quadruped robot (4 legs × 2 joints each) to walk forward
using reinforcement learning. The robot is modeled after the SunFounder PiDog
with position-controlled servos.

Observation space (27-dim):
  - 8 joint positions   (normalized: degrees / 45)
  - 8 joint velocities  (normalized: rad_s / 10)
  - 4 torso quaternion  (w, x, y, z — raw)
  - 3 torso linear velocity (m/s — raw)
  - 3 torso angular velocity from IMU gyro (rad/s — raw)
  - 1 torso height      (normalized: meters / 0.05)

Action space (8-dim, continuous [-1, 1]):
  - Maps to joint position targets: STAND_DEG ± ACTION_RANGE degrees
  - Control smoothing: 80% previous target + 20% new target per step

Physics:
  - Simulation timestep: 2ms, 10 substeps per control step → 50Hz control rate
  - Max episode: 1000 steps (20 seconds)
  - Standing height with STAND pose: ~0.05m (not 0.12m — legs are bent)
"""

import os
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import mujoco

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pidog.xml")

# Standing pose from real robot (matches sim_trot.py).
# Joint order: [LF_hip, LF_knee, RF_hip, RF_knee, LH_hip, LH_knee, RH_hip, RH_knee]
# Right-side joints are negated due to mirrored axis convention in pidog.xml.
STAND_DEG = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)

# Max deviation from STAND pose per action dimension.
# With STAND values up to ±35 and ctrlrange=±60, this gives 10° headroom.
ACTION_RANGE = 15.0


class PiDogEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 25}

    def __init__(self, render_mode=None):
        super().__init__()
        self.render_mode = render_mode

        self.model = mujoco.MjModel.from_xml_path(MODEL_PATH)
        self.data = mujoco.MjData(self.model)

        self.n_substeps = 10       # 10 × 2ms = 20ms per control step (50Hz)
        self.max_episode_steps = 1000  # 1000 × 20ms = 20 seconds max

        self.action_space = spaces.Box(-1.0, 1.0, shape=(8,), dtype=np.float32)
        self.observation_space = spaces.Box(
            -np.inf, np.inf, shape=(27,), dtype=np.float32
        )

        self._renderer = None
        if render_mode == "rgb_array":
            self._renderer = mujoco.Renderer(self.model, height=480, width=640)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)
        self._last_ctrl_deg = STAND_DEG.copy()

        # Cache body/sensor IDs for reward computation and observation
        self._torso_body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "torso"
        )
        self._gyro_sensor_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SENSOR, "imu_gyro"
        )

    def _get_obs(self):
        """Build 27-dim observation vector with manual normalization."""
        # qpos layout: [x, y, z, qw, qx, qy, qz, j0..j7] (15 total)
        # qvel layout: [vx, vy, vz, wx, wy, wz, j0..j7]   (14 total)
        joint_pos = self.data.qpos[7:15].copy()
        joint_pos_norm = np.degrees(joint_pos) / 45.0  # ~[-1, 1] for ±45° range

        joint_vel = self.data.qvel[6:14].copy()
        joint_vel_norm = joint_vel / 10.0  # rough scaling for rad/s

        torso_quat = self.data.qpos[3:7].copy()   # [w, x, y, z]
        torso_vel = self.data.qvel[0:3].copy()     # [vx, vy, vz] in m/s

        # Read gyroscope from IMU sensor (angular velocity in body frame)
        gyro_adr = self.model.sensor_adr[self._gyro_sensor_id]
        gyro_dim = self.model.sensor_dim[self._gyro_sensor_id]
        torso_gyro = self.data.sensordata[gyro_adr:gyro_adr + gyro_dim].copy()

        # Normalize height so ~1.0 when standing (actual height ≈ 0.05m)
        torso_z = np.array([self.data.qpos[2] / 0.05])

        return np.concatenate([
            joint_pos_norm,   # 8
            joint_vel_norm,   # 8
            torso_quat,       # 4
            torso_vel,        # 3
            torso_gyro,       # 3
            torso_z,          # 1
        ]).astype(np.float32)

    def _compute_reward(self, action, terminated):
        """Compute shaped reward encouraging forward locomotion while staying upright.

        Reward components:
          + 20.0 × forward_vel    Primary objective: walk forward (high weight
                                  needed because robot speed is ~0.05 m/s)
          + 1.0  alive bonus      Encourages survival (0 if moving backward)
          - 0.05 × energy         Penalize large actuator commands (sum of squared actions)
          - 2.0  × orientation    Penalize torso tilt (xy components of body up-vector)
          - 3.0  × height_dev     Penalize deviation from 0.05m standing height
          - 1.0  × lateral_vel    Discourage sideways drift
          - 1.0  × vertical_vel   Discourage bouncing
          - 0.05 × smoothness     Penalize jerky action changes between steps
          - 10.0 on termination   One-time penalty for falling
        """
        forward_vel = self.data.qvel[0]
        lateral_vel = self.data.qvel[1]
        vertical_vel = self.data.qvel[2]
        torso_z = self.data.qpos[2]

        alive = 1.0 if forward_vel > -0.01 else 0.0

        energy_penalty = np.sum(np.square(action)) * 0.05

        # Extract torso up-vector from rotation matrix; penalize xy tilt
        body_xmat = self.data.xmat[self._torso_body_id].reshape(3, 3)
        up_vec = body_xmat[:, 2]
        orientation_penalty = np.sum(np.square(up_vec[:2])) * 2.0

        height_target = 0.05  # actual standing height with STAND_DEG bent legs
        height_penalty = abs(torso_z - height_target) * 3.0

        lateral_penalty = abs(lateral_vel) * 1.0
        vertical_penalty = abs(vertical_vel) * 1.0

        # Penalize difference from previous action to encourage smooth gaits
        smoothness_penalty = np.sum(np.square(action - self._last_action)) * 0.05

        reward = (
            20.0 * forward_vel
            + alive
            - energy_penalty
            - orientation_penalty
            - height_penalty
            - lateral_penalty
            - vertical_penalty
            - smoothness_penalty
        )

        if terminated:
            reward -= 10.0

        return reward

    def _is_terminated(self):
        """End episode if the robot falls (height < 25mm or tilt > 60°)."""
        torso_z = self.data.qpos[2]
        if torso_z < 0.025:
            return True

        # Quaternion w < 0.5 corresponds to ~60° tilt from upright
        quat = self.data.qpos[3:7]
        if abs(quat[0]) < 0.5:
            return True

        return False

    def reset(self, seed=None, options=None):
        """Reset to standing pose by letting actuators settle from straight legs.

        After mj_resetData, the torso starts at 0.12m with straight legs (from XML).
        We set ctrl to STAND_DEG and simulate 250 steps (0.5s) so the position
        actuators gradually bend the legs into the standing pose, settling at ~0.05m.
        This matches the approach in sim_trot.py and avoids the instability caused
        by directly setting bent-leg qpos at the wrong height.
        """
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)

        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = STAND_DEG
        self._last_ctrl_deg = STAND_DEG.copy()

        # Settle into standing pose (250 steps × 2ms = 0.5s)
        for _ in range(250):
            mujoco.mj_step(self.model, self.data)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)
        return self._get_obs(), {}

    def step(self, action):
        """Apply action, advance physics, return (obs, reward, terminated, truncated, info).

        Action pipeline:
          1. Clip action to [-1, 1]
          2. Map to target joint angles: STAND_DEG + action × ACTION_RANGE
          3. Smooth with previous target: 80% old + 20% new (prevents jerky movement)
          4. Set MuJoCo ctrl and run 10 substeps (20ms of physics)
        """
        action = np.asarray(action, dtype=np.float32)
        prev_action = self._last_action.copy()

        target_ctrl_deg = STAND_DEG + action * ACTION_RANGE

        # Exponential smoothing prevents sudden servo jumps (important for sim-to-real)
        ctrl_deg = 0.8 * self._last_ctrl_deg + 0.2 * target_ctrl_deg
        self.data.ctrl[:] = ctrl_deg

        for _ in range(self.n_substeps):
            mujoco.mj_step(self.model, self.data)

        self._step_count += 1

        obs = self._get_obs()
        terminated = self._is_terminated()

        # Smoothness penalty needs the *previous* action, so swap around the update
        self._last_action = prev_action
        reward = self._compute_reward(action, terminated)

        self._last_action = action.copy()
        self._last_ctrl_deg = ctrl_deg.copy()

        truncated = self._step_count >= self.max_episode_steps

        return obs, reward, terminated, truncated, {}

    def render(self):
        if self._renderer is not None:
            self._renderer.update_scene(self.data)
            return self._renderer.render()
        return None

    def close(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None


if __name__ == "__main__":
    env = PiDogEnv()
    obs, info = env.reset()
    print(f"Observation shape: {obs.shape}")
    print(f"Action space: {env.action_space}")
    print(f"Initial torso height: {env.data.qpos[2]:.4f} m")

    print("\n--- Standing test (action=0 for 100 steps) ---")
    total_reward = 0
    for i in range(100):
        action = np.zeros(8, dtype=np.float32)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        if terminated:
            print(f"  Fell at step {i}!")
            break
    else:
        print(f"  Survived 100 steps! Reward: {total_reward:.2f}")
        print(f"  Final height: {env.data.qpos[2]:.4f} m")
        print(f"  Forward: {env.data.qpos[0]*1000:.1f} mm")

    print("\n--- Random actions test (200 steps) ---")
    obs, _ = env.reset()
    total_reward = 0
    for i in range(200):
        action = env.action_space.sample() * 0.3
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward
        if terminated:
            print(f"  Fell at step {i}")
            break
    else:
        print(f"  Survived 200 steps!")
    print(f"  Steps: {i+1}, Reward: {total_reward:.2f}")
    print(f"  Final height: {env.data.qpos[2]:.4f} m")

    env.close()
