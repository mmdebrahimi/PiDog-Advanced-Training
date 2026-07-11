#!/usr/bin/env python3
# NOT THE CANONICAL ENV. This copy has a 24-dim observation and NO scripted base gait.
# The canonical training env is the repo-root `pidog_env.py`: 29-dim obs, policy emits a small
# RESIDUAL on a known-symmetric scripted diagonal trot. Policies trained against it pass
# `eval_mvp.py` (run15: 432 mm forward, 1000 steps).
#
# A sibling 27-dim direct-control env was benchmarked on 2026-07-09: 8 PPO configurations, none
# exceeded ~15 mm forward (standing) or survived a forward dive past step ~35. THIS file has not
# itself been benchmarked -- it is flagged, not condemned. Prefer the root env; if you must use
# this one, gate it with `eval_mvp.py` before believing any result.

"""Gymnasium environment for PiDog locomotion in MuJoCo.

Observation (24-dim):
  - 8 joint positions (normalized to ~[-1, 1])
  - 8 joint velocities (normalized)
  - 4 torso quaternion (w, x, y, z)
  - 3 torso linear velocity (m/s)
  - 1 torso height (normalized)

Action (8-dim):
  - 8 joint position deltas from STAND pose, normalized to [-1, 1]
  - Mapped to STAND ± 20° (action=0 → stable stand)
"""

import os
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import mujoco

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pidog.xml")

# Stand pose in degrees — action=0 produces this stable pose
# In sim, zero angles = legs straight down = stable at ~124mm height
# (Real robot uses [25,35,-25,-35,35,35,-35,-35] but sim kinematics differ)
STAND_DEG = np.array([0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float64)
ACTION_RANGE = 30.0  # ±30° around stand


class PiDogEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 25}

    def __init__(self, render_mode=None):
        super().__init__()
        self.render_mode = render_mode

        self.model = mujoco.MjModel.from_xml_path(MODEL_PATH)
        self.data = mujoco.MjData(self.model)

        # Control at 50Hz: 10 sim steps per action (dt=0.002 * 10 = 20ms)
        self.n_substeps = 10
        self.max_episode_steps = 1000  # 20 seconds at 50Hz

        # Action: 8 joint deltas from STAND, normalized [-1, 1]
        self.action_space = spaces.Box(-1.0, 1.0, shape=(8,), dtype=np.float32)

        # Observation: joints(8) + joint_vel(8) + quat(4) + linvel(3) + height(1) = 24
        self.observation_space = spaces.Box(
            -np.inf, np.inf, shape=(24,), dtype=np.float32
        )

        self._renderer = None
        if render_mode == "rgb_array":
            self._renderer = mujoco.Renderer(self.model, height=480, width=640)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)

        # Body index for torso (for xmat lookup)
        self._torso_body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "torso"
        )

    def _get_obs(self):
        # Joint positions (8 actuated joints, skip root freejoint qpos[0:7])
        joint_pos = self.data.qpos[7:15].copy()
        joint_pos_norm = np.degrees(joint_pos) / 45.0  # normalize to ~[-1, 1]

        # Joint velocities
        joint_vel = self.data.qvel[6:14].copy()
        joint_vel_norm = joint_vel / 10.0

        # Torso quaternion
        torso_quat = self.data.qpos[3:7].copy()

        # Torso linear velocity
        torso_vel = self.data.qvel[0:3].copy()

        # Torso height (normalized by standing height ~0.12m)
        torso_z = np.array([self.data.qpos[2] / 0.12])

        return np.concatenate([
            joint_pos_norm,  # 8
            joint_vel_norm,  # 8
            torso_quat,      # 4
            torso_vel,       # 3
            torso_z,         # 1
        ]).astype(np.float32)

    def _compute_reward(self, action, terminated):
        # Forward velocity (x-axis)
        forward_vel = self.data.qvel[0]

        # Alive bonus — only if not going backward
        alive = 1.0 if forward_vel > -0.01 else 0.0

        # Energy penalty — from normalized action (already [-1, 1])
        energy = np.sum(np.square(action)) * 0.05

        # Orientation penalty — penalize tilt (pitch/roll), NOT yaw
        # Get the body z-axis in world frame; for upright robot it should be [0, 0, 1]
        body_xmat = self.data.xmat[self._torso_body_id].reshape(3, 3)
        up_vec = body_xmat[:, 2]  # z-column = body's up direction in world
        orientation_penalty = np.sum(np.square(up_vec[:2])) * 2.0

        reward = 2.0 * forward_vel + alive - energy - orientation_penalty

        # Heavy penalty for falling
        if terminated:
            reward -= 10.0

        return reward

    def _is_terminated(self):
        torso_z = self.data.qpos[2]
        if torso_z < 0.015:
            return True
        # Flipped: quaternion w component too small
        quat = self.data.qpos[3:7]
        if abs(quat[0]) < 0.5:
            return True
        return False

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)

        # Set initial pose: STAND with small noise
        stand_rad = np.radians(STAND_DEG)
        noise = self.np_random.uniform(-0.02, 0.02, size=8)
        self.data.qpos[2] = 0.12  # initial height (settle will adjust)
        self.data.qpos[7:15] = stand_rad + noise
        self.data.ctrl[:] = STAND_DEG

        # Let it settle (200 steps = 400ms at dt=0.002)
        for _ in range(200):
            mujoco.mj_step(self.model, self.data)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)
        return self._get_obs(), {}

    def step(self, action):
        self._last_action = action.copy()

        # Map action [-1, 1] to degrees: STAND + action * 20°
        ctrl_deg = STAND_DEG + action * ACTION_RANGE
        self.data.ctrl[:] = ctrl_deg

        for _ in range(self.n_substeps):
            mujoco.mj_step(self.model, self.data)

        self._step_count += 1

        obs = self._get_obs()
        terminated = self._is_terminated()
        reward = self._compute_reward(action, terminated)
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
    # Sanity test
    env = PiDogEnv()
    obs, info = env.reset()
    print(f"Observation shape: {obs.shape}")
    print(f"Action space: {env.action_space}")
    print(f"Initial torso height: {env.data.qpos[2]:.4f} m")

    # Test: action=0 should produce stable standing
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

    # Test: random small actions
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
