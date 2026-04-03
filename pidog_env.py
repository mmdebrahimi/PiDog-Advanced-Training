#!/usr/bin/env python3
"""Gymnasium environment for PiDog locomotion in MuJoCo.

Observation (27-dim):
  - 8 joint positions
  - 8 joint velocities
  - 4 torso quaternion (w, x, y, z)
  - 3 torso linear velocity
  - 3 torso angular velocity (gyro)
  - 1 torso height

Action (8-dim):
  - 8 joint position deltas from STAND pose, normalized to [-1, 1]
  - Mapped to STAND ± 15°
"""

import os
import numpy as np
import gymnasium as gym
from gymnasium import spaces
import mujoco

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pidog.xml")

STAND_DEG = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)
# ACTION_RANGE = 20.0  # reduced from 30 to 20 for safer exploration
ACTION_RANGE = 15.0  # reduced from 30 to 20 for safer exploration


class PiDogEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 25}

    def __init__(self, render_mode=None):
        super().__init__()
        self.render_mode = render_mode

        self.model = mujoco.MjModel.from_xml_path(MODEL_PATH)
        self.data = mujoco.MjData(self.model)

        self.n_substeps = 10
        self.max_episode_steps = 1000

        self.action_space = spaces.Box(-1.0, 1.0, shape=(8,), dtype=np.float32)

        # joints(8) + joint_vel(8) + quat(4) + linvel(3) + gyro(3) + height(1) = 27
        self.observation_space = spaces.Box(
            -np.inf, np.inf, shape=(27,), dtype=np.float32
        )

        self._renderer = None
        if render_mode == "rgb_array":
            self._renderer = mujoco.Renderer(self.model, height=480, width=640)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)
        self._last_ctrl_deg = STAND_DEG.copy()

        self._torso_body_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "torso"
        )

        self._gyro_sensor_id = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SENSOR, "imu_gyro"
        )

    def _get_obs(self):
        joint_pos = self.data.qpos[7:15].copy()
        joint_pos_norm = np.degrees(joint_pos) / 45.0

        joint_vel = self.data.qvel[6:14].copy()
        joint_vel_norm = joint_vel / 10.0

        torso_quat = self.data.qpos[3:7].copy()
        torso_vel = self.data.qvel[0:3].copy()

        gyro_adr = self.model.sensor_adr[self._gyro_sensor_id]
        gyro_dim = self.model.sensor_dim[self._gyro_sensor_id]
        torso_gyro = self.data.sensordata[gyro_adr:gyro_adr + gyro_dim].copy()

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
        forward_vel = self.data.qvel[0]
        lateral_vel = self.data.qvel[1]
        vertical_vel = self.data.qvel[2]
        torso_z = self.data.qpos[2]

        alive = 1.0 if forward_vel > -0.01 else 0.0

        energy_penalty = np.sum(np.square(action)) * 0.05

        body_xmat = self.data.xmat[self._torso_body_id].reshape(3, 3)
        up_vec = body_xmat[:, 2]
        orientation_penalty = np.sum(np.square(up_vec[:2])) * 2.0

        height_target = 0.05
        height_penalty = abs(torso_z - height_target) * 5.0

        lateral_penalty = abs(lateral_vel) * 1.0
        vertical_penalty = abs(vertical_vel) * 1.0

        smoothness_penalty = np.sum(np.square(action - self._last_action)) * 0.05

        reward = (
            2.0 * forward_vel
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
        torso_z = self.data.qpos[2]
        if torso_z < 0.025:
            return True

        quat = self.data.qpos[3:7]
        if abs(quat[0]) < 0.5:
            return True

        return False

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)

        # Don't pre-set joint qpos — let actuators pull joints to STAND
        # gradually from default (straight-leg) position, matching sim_trot.py.
        # With STAND_DEG bent legs, actual standing height is ~0.05m, not 0.12m.
        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = STAND_DEG
        self._last_ctrl_deg = STAND_DEG.copy()

        for _ in range(250):
            mujoco.mj_step(self.model, self.data)

        self._step_count = 0
        self._last_action = np.zeros(8, dtype=np.float32)
        return self._get_obs(), {}

    def step(self, action):
        action = np.asarray(action, dtype=np.float32)
        prev_action = self._last_action.copy()

        target_ctrl_deg = STAND_DEG + action * ACTION_RANGE

        # light control smoothing
        ctrl_deg = 0.8 * self._last_ctrl_deg + 0.2 * target_ctrl_deg
        self.data.ctrl[:] = ctrl_deg

        for _ in range(self.n_substeps):
            mujoco.mj_step(self.model, self.data)

        self._step_count += 1

        obs = self._get_obs()
        terminated = self._is_terminated()

        # reward uses previous action for smoothness penalty
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
