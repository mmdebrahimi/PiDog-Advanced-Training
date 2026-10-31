#!/usr/bin/env python3
"""Gymnasium environment for PiDog quadruped locomotion in MuJoCo.

Trains an 8-DOF quadruped robot (4 legs × 2 joints each) to walk forward
using reinforcement learning. The robot is modeled after the SunFounder PiDog
with position-controlled servos.

Observation space (27-dim):
  - 8 joint positions   (normalized: degrees / 45)
  - 8 joint velocities  (normalized: rad/s / 10)
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
  - Standing height with STAND pose: ~0.053m

IMPORTANT: MuJoCo ctrl expects RADIANS at runtime, even when compiler angle="degree".
The degree setting only affects XML attribute parsing, not runtime ctrl values.
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
# With STAND values up to ±35 and ctrlrange=±80, this gives ample headroom.
ACTION_RANGE = 15.0

# --- Residual control around the scripted symmetric trot (sim_trot.py) ---
# The policy outputs a SMALL residual on top of a known-symmetric diagonal trot,
# so the asymmetric one-leg-up exploit (which curved all 12 prior reward-shaped
# runs) becomes a large, costly residual. Base gait is correct by construction.
GAIT_LIFT = 30.0    # knee bend increase for swing (matches sim_trot.py)
GAIT_SWING = 10.0   # hip fwd/back offset for swing/stance (matches sim_trot.py)
RESIDUAL_DEG = 12.0  # run15: back to 12 (run13's value gave straight+symmetric yaw=5deg;
                     # run14's 18 over-authorized -> broke symmetric base -> flail+fall)


class PiDogEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 25}

    def __init__(self, render_mode=None, base_gait=None):
        super().__init__()
        self.render_mode = render_mode

        # Base gait the residual rides on: "trot" (default, run15-21 lineage) or
        # "crawl" (one-leg-at-a-time, power-budget gait — the robot browns out when
        # 8 servos move simultaneously, which the trot demands; see
        # deploy/power_audit.py). Env var PIDOG_BASE_GAIT reaches SubprocVecEnv
        # workers, same pattern as PIDOG_DR / PIDOG_SMOOTH.
        self.base_gait = base_gait or os.environ.get("PIDOG_BASE_GAIT", "trot")
        if self.base_gait not in ("trot", "crawl"):
            raise ValueError(f"base_gait must be 'trot' or 'crawl', got {self.base_gait!r}")

        self.model = mujoco.MjModel.from_xml_path(MODEL_PATH)
        self.data = mujoco.MjData(self.model)

        # Domain randomization (sim-to-real robustness) — enabled via env PIDOG_DR=1.
        # OFF by default so eval/diagnostics measure cleanly.
        self._dr = os.environ.get("PIDOG_DR", "0") == "1"
        self._nominal_body_mass = self.model.body_mass.copy()
        self._nominal_friction = self.model.geom_friction.copy()
        self._smooth_alpha = 0.8

        # Gait-SMOOTHNESS reward terms — enabled via env PIDOG_SMOOTH=1. OFF by
        # default so the run18/19 baseline reward is reproduced exactly. Targets the
        # persistent LH-back-foot-held-up asymmetry (phase-correct planting), air-pawing
        # (over-lift), and residual thrash (jerk). MUST be warm-started off an already-
        # walking policy — a jerk penalty from scratch collapsed runs 16/17 to standing.
        self._smooth = os.environ.get("PIDOG_SMOOTH", "0") == "1"
        # Extra body-frame lateral penalty (smooth-mode only), env-tunable. Default 0 =
        # reproduces run21 exactly. Used to kill run21's under-DR CRAB regression without
        # touching the run18/19 baseline reward.
        self._lat_extra = float(os.environ.get("PIDOG_LAT_EXTRA", "0"))
        # Tunable smoothness coefficients (defaults reproduce run21). Lets the overnight
        # sweep try GENTLER shaping that keeps DR-forward progress.
        self._k_contact = float(os.environ.get("PIDOG_SMOOTH_CONTACT", "0.15"))
        self._k_overlift = float(os.environ.get("PIDOG_SMOOTH_OVERLIFT", "2.0"))
        self._k_jerk = float(os.environ.get("PIDOG_SMOOTH_JERK", "0.10"))

        self.n_substeps = 10          # 10 × 2ms = 20ms per control step (50Hz)
        self.max_episode_steps = 1000  # 1000 × 20ms = 20 seconds max

        self.action_space = spaces.Box(-1.0, 1.0, shape=(8,), dtype=np.float32)
        self.observation_space = spaces.Box(
            -np.inf, np.inf, shape=(29,), dtype=np.float32  # +2 gait-clock [sin, cos]
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

        # Gait-clock: a phase signal that advances each control step. The policy
        # sees [sin, cos] of it and is rewarded for trotting in time with it.
        # Foot order LF, RF, LH, RH; diagonal trot pairs = (LF,RH) and (RF,LH).
        self._foot_ids = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, f)
            for f in ("lf_foot", "rf_foot", "lh_foot", "rh_foot")
        ]
        # Cadence: trot 2.0 Hz (run15-21 lineage). Crawl 1.0 Hz — each leg gets a
        # 250ms swing quarter; faster would demand near-trot servo speeds and
        # defeat the power-sequencing purpose.
        self.GAIT_FREQ_HZ = 2.0 if self.base_gait == "trot" else 1.0
        self._phase_inc = 2.0 * np.pi * self.GAIT_FREQ_HZ / 50.0  # 50Hz control
        self._phase = 0.0
        # Residual authority is gait-specific (trot 12 = run15-21 lineage, pinned
        # by deploy parity tests; crawl 18 — see CRAWL_RESIDUAL_DEG comment).
        self._residual_deg = RESIDUAL_DEG if self.base_gait == "trot" else self.CRAWL_RESIDUAL_DEG
        if self._smooth and self.base_gait != "trot":
            raise ValueError("PIDOG_SMOOTH shaping encodes the trot stance schedule; "
                             "it is not defined for base_gait='crawl'")
        self._yaw0 = 0.0                              # initial heading, set in reset()
        self.CONTACT_Z = 0.012                        # foot "down" below 12mm

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

        # Normalize height so ~1.0 when standing (actual height ≈ 0.053m)
        torso_z = np.array([self.data.qpos[2] / 0.05])

        clock = np.array([np.sin(self._phase), np.cos(self._phase)])  # gait-clock

        obs = np.concatenate([
            joint_pos_norm,   # 8
            joint_vel_norm,   # 8
            torso_quat,       # 4
            torso_vel,        # 3
            torso_gyro,       # 3
            torso_z,          # 1
            clock,            # 2  (sin, cos of gait phase)
        ]).astype(np.float32)
        # DR: sensor noise on the 27 measured dims (NOT the 2 clock dims — those are exact on deploy too)
        if self._dr:
            obs[:27] += self.np_random.normal(0, 0.02, size=27).astype(np.float32)
        return obs

    def _scripted_trot_deg(self):
        """Scripted symmetric diagonal-trot target joints (deg) for the current phase.

        Phase-driven version of sim_trot.py's 2-frame gait, locked to the gait clock:
        sin(phase) >= 0 -> frame A (LF,RH stance / RF,LH swing); else frame B.
        Joint order [LF_hip, LF_knee, RF_hip, RF_knee, LH_hip, LH_knee, RH_hip, RH_knee].
        """
        s = STAND_DEG
        L, S = GAIT_LIFT, GAIT_SWING
        if np.sin(self._phase) >= 0:
            # Frame A: LF+RH stance (hip fwd, knee normal), RF+LH swing (hip back, knee bent)
            return np.array([
                s[0] - S, s[1],          # LF stance
                s[2] - S, s[3] - L,      # RF swing
                s[4] + S, s[5] + L,      # LH swing
                s[6] + S, s[7],          # RH stance
            ], dtype=np.float64)
        # Frame B: RF+LH stance, LF+RH swing
        return np.array([
            s[0] + S, s[1] + L,          # LF swing
            s[2] + S, s[3],              # RF stance
            s[4] - S, s[5],              # LH stance
            s[6] - S, s[7] - L,          # RH swing
        ], dtype=np.float64)

    # Crawl swing order: LF, RH, RF, LH (sim leg indices 0,3,1,2) — mirrors the
    # stock SunFounder lib's one-leg-at-a-time lift sequence.
    CRAWL_ORDER = (0, 3, 1, 2)
    # Crawl-specific base amplitudes + residual authority (2026-10-31 sweep over
    # 72 scripted-only configs x both stride signs: EVERY config drifts backward
    # from foot slip — same structural bias as the trot base's -74mm standalone —
    # and backward drift scales with amplitude/cadence, so the least-backward
    # base wins: flipped stride, S=10, L=20, 1.0Hz = -10mm/5s. The residual gets
    # 18 deg authority (vs trot's 12) because the gentle 1Hz base gives the
    # policy less dynamics to shape; run14's over-authorization failure was
    # dynamic flail on the 2Hz trot, which the statically-stable crawl avoids.)
    CRAWL_SWING = 10.0
    CRAWL_LIFT = 20.0
    CRAWL_RESIDUAL_DEG = 18.0

    def _scripted_crawl_deg(self):
        """Scripted one-leg-at-a-time crawl target joints (deg) for the current phase.

        Power-budget base gait: exactly one leg swings per quarter cycle while the
        three stance legs drift their stride back linearly (net body motion), so at
        most one leg's pair of servos moves hard at any tick — matching the
        hardware's sequenced-motion power envelope.

        Per leg, a stride variable u in [-1, +1]: cosine-eased -1 -> +1 during the
        leg's swing quarter (with a sin-profile knee lift), linear +1 -> -1 drift
        across its three stance quarters. Sign conventions are lifted from
        _scripted_trot_deg: left legs swing (+S hip, +L knee), right legs mirrored.
        """
        s = STAND_DEG
        L, S = self.CRAWL_LIFT, self.CRAWL_SWING
        phase = self._phase % (2 * np.pi)
        quarter = int(phase // (np.pi / 2.0)) % 4
        t = (phase % (np.pi / 2.0)) / (np.pi / 2.0)  # 0..1 within the quarter

        out = np.array(s, dtype=np.float64)
        for slot, leg in enumerate(self.CRAWL_ORDER):
            right = leg in (1, 3)                 # RF, RH mirrored signs
            # Stride sign FLIPPED vs the trot convention (measured least-backward
            # in the 2026-10-31 sweep; see class-constant comment).
            hip_sign = S if right else -S
            knee_sign = -L if right else L
            if slot == quarter:                   # swing: stride -1 -> +1, knee lifts
                u = -np.cos(np.pi * t)            # cosine ease
                lift = np.sin(np.pi * t)
            else:                                 # stance: linear drift +1 -> -1
                since_swing = (quarter - slot) % 4          # 1..3 quarters since swing
                prog = (since_swing - 1 + t) / 3.0          # 0..1 across stance
                u = 1.0 - 2.0 * prog
                lift = 0.0
            out[2 * leg] += hip_sign * u
            out[2 * leg + 1] += knee_sign * lift
        return out

    def _scripted_base_deg(self):
        """Dispatch: the scripted base gait the residual policy rides on."""
        if self.base_gait == "crawl":
            return self._scripted_crawl_deg()
        return self._scripted_trot_deg()

    def _compute_reward(self, action, terminated):
        """Residual-mode reward: go forward along the initial heading, straight + upright.

        The base gait is the scripted SYMMETRIC trot, so there is NO 'discover-a-gait'
        contact reward (that is what every prior reward-shaped run gamed into an
        asymmetric curve). Here `action` IS a small residual, so we only need:
        forward progress along +x (initial heading), heading discipline (don't curve),
        no lateral slide, stay upright/at height, and keep the residual small.
        """
        forward_vel = self.data.qvel[0]   # world +x == initial heading (reset faces +x)
        lateral_vel = self.data.qvel[1]
        torso_z = self.data.qpos[2]

        # Yaw deviation from the initial (+x) heading
        q = self.data.qpos[3:7]
        yaw = np.arctan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2))
        yaw_err = np.arctan2(np.sin(yaw - self._yaw0), np.cos(yaw - self._yaw0))

        # Upright + height keep
        body_xmat = self.data.xmat[self._torso_body_id].reshape(3, 3)
        up_vec = body_xmat[:, 2]
        orientation_penalty = np.sum(np.square(up_vec[:2])) * 2.0
        height_penalty = abs(torso_z - 0.05) * 3.0

        reward = (
            6.0 * forward_vel                       # run18: back to 6 (MVP value); action-rate penalty (not forward) was killing motion
            + 0.5                                   # alive
            - 0.8 * abs(yaw_err)                    # heading discipline (don't curve)
            - 0.8 * abs(lateral_vel)                # run18: 0.3->0.5, GENTLE drift trim (run16's 0.6+action-rate over-corrected to standing)
            - 0.05 * np.sum(np.square(action))      # small residual penalty (action = residual)
            # run18: action-rate penalty REMOVED — it was anti-motion (collapsed runs 16/17 to standing)
            - orientation_penalty
            - height_penalty
        )

        # --- Gait-smoothness shaping (warm-start only; baseline reward unchanged) ---
        if self._smooth:
            foot_z = np.array([self.data.site_xpos[fid][2] for fid in self._foot_ids])  # LF,RF,LH,RH
            down = foot_z < self.CONTACT_Z
            # Phase-correct stance schedule (matches _scripted_trot_deg frames)
            if np.sin(self._phase) >= 0:
                stance = np.array([True, False, False, True])   # frame A: LF,RH down
            else:
                stance = np.array([False, True, True, False])   # frame B: RF,LH down
            # Reward each foot matching its phase-correct contact state (centered at 2/4):
            # pulls the held-up LH foot DOWN during its stance phase -> symmetric, smoother.
            contact_reward = self._k_contact * (float(np.sum(down == stance)) - 2.0)
            # Discourage air-pawing: penalize foot height above 40mm (LH lifts ~100mm).
            overlift_penalty = self._k_overlift * float(np.sum(np.clip(foot_z - 0.040, 0.0, None)))
            # Gentle jerk penalty on the residual (warm-start avoids the 16/17 collapse).
            jerk_penalty = self._k_jerk * float(np.mean(np.square(action - self._last_action)))
            reward += contact_reward - overlift_penalty - jerk_penalty
            # Extra lateral trim to fix the under-DR crab (default 0 = run21 unchanged).
            reward -= self._lat_extra * abs(lateral_vel)

        if terminated:
            reward -= 50.0

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
        """Reset to standing pose with pre-set joints at correct height.

        Pre-sets joint angles to STAND (in radians) and torso at 0.08m,
        then settles for 500 physics steps (1.0s) so the robot reaches
        its natural standing height of ~0.053m.
        """
        super().reset(seed=seed)
        mujoco.mj_resetData(self.model, self.data)

        # --- Domain randomization: perturb physics each episode for sim-to-real ---
        if self._dr:
            self.model.body_mass[:] = self._nominal_body_mass * self.np_random.uniform(0.80, 1.25)
            self.model.geom_friction[:] = self._nominal_friction
            self.model.geom_friction[:, 0] = self._nominal_friction[:, 0] * self.np_random.uniform(0.6, 1.4)
            self._smooth_alpha = float(self.np_random.uniform(0.70, 0.88))  # servo-speed variation
        else:
            self._smooth_alpha = 0.8

        # Pre-set joints and height to avoid violent drop from 0.12m
        self.data.qpos[2] = 0.08
        self.data.qpos[7:15] = np.radians(STAND_DEG)
        if self._dr:
            self.data.qpos[7:15] += self.np_random.uniform(-0.05, 0.05, size=8)  # initial-pose jitter (rad)
        self.data.qvel[:] = 0.0
        self.data.ctrl[:] = np.radians(STAND_DEG)  # MuJoCo expects RADIANS
        self._last_ctrl_deg = STAND_DEG.copy()

        # Settle into standing pose (500 steps × 2ms = 1.0s)
        for _ in range(500):
            mujoco.mj_step(self.model, self.data)

        self._step_count = 0
        self._phase = 0.0
        # Capture the initial heading (yaw) so the reward can keep the trot pointed forward
        q = self.data.qpos[3:7]
        self._yaw0 = float(np.arctan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] ** 2 + q[3] ** 2)))
        self._last_action = np.zeros(8, dtype=np.float32)
        return self._get_obs(), {}

    def step(self, action):
        """Apply action, advance physics 20ms, return (obs, reward, terminated, truncated, info).

        Action pipeline:
          1. Map action [-1,1] to target joint angles: STAND_DEG ± ACTION_RANGE
          2. Smooth with previous target: 80% old + 20% new
          3. Convert to radians and set MuJoCo ctrl
          4. Run 10 substeps (20ms of physics)
        """
        action = np.asarray(action, dtype=np.float32)
        prev_action = self._last_action.copy()

        # Residual control: scripted base gait (trot or crawl) + small learned residual
        target_ctrl_deg = self._scripted_base_deg() + action * self._residual_deg

        # Exponential smoothing prevents sudden servo jumps (sim-to-real friendly)
        a = self._smooth_alpha
        ctrl_deg = a * self._last_ctrl_deg + (1 - a) * target_ctrl_deg
        self.data.ctrl[:] = np.radians(ctrl_deg)  # MuJoCo expects RADIANS

        # DR: occasional random body shove (robustness to bumps / uneven floor)
        if self._dr and self.np_random.random() < 0.01:
            self.data.qvel[0:2] += self.np_random.uniform(-0.15, 0.15, size=2)

        for _ in range(self.n_substeps):
            mujoco.mj_step(self.model, self.data)

        self._step_count += 1
        self._phase += self._phase_inc   # advance the gait clock

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
