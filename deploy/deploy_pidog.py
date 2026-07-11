"""Deploy trained PPO policy to physical SunFounder PiDog.

Runs a 50 Hz inference loop:
  read IMU + joint encoders -> build 29-dim obs -> MLP forward -> servo targets.

Observation layout (29 dims) must match sim (pidog_env.py:176):
  [8] joint_pos_norm   = degrees(qpos) / 45.0
  [8] joint_vel_norm   = qvel / 10.0          (finite-diff)
  [4] torso_quat       = [w, x, y, z]         (IMU)
  [3] torso_vel        = [vx, vy, vz] m/s     (NO SENSOR -> zeros)
  [3] torso_gyro       = [wx, wy, wz] rad/s   (IMU)
  [1] torso_z          = height / 0.082       (NO SENSOR -> 1.0)
  [2] gait_clock       = [sin(phase), cos(phase)]

Action -> servo:
  target_deg = STAND_DEG + clip(action, -1, 1) * ACTION_RANGE
  smoothed   = 0.8 * last_deg + 0.2 * target_deg
  Map each smoothed joint angle to the PiDog servo ID and apply.

Joint order (must match sim XML pidog.xml):
  0: LF_hip   1: LF_knee
  2: RF_hip   3: RF_knee
  4: LH_hip   5: LH_knee
  6: RH_hip   7: RH_knee

SAFETY: Start with the robot on a tether / held. First test should be
standing pose only (--stand). Only release into full policy after servos
hold STAND_DEG reliably.
"""
import argparse
import time
import numpy as np

# ===== Constants (MUST MATCH sim pidog_env.py) =====
STAND_DEG = np.array([25, 35, 25, 35, -25, -35, -25, -35], dtype=np.float64)
ACTION_RANGE = 15.0
SMOOTHING_ALPHA = 0.8
GAIT_PERIOD_STEPS = 25           # 25 steps * 20ms = 500ms (2.0 Hz) -- MUST match trained env GAIT_FREQ_HZ=2.0
DT = 0.02                        # 50 Hz
STAND_HEIGHT_M = 0.082

# --- Residual control (run15 straight-trot policy) ---
# The policy outputs a RESIDUAL on a scripted symmetric diagonal trot, NOT a full
# action. Reproduce the training-time control: ctrl = scripted_trot(phase) + residual.
# These are in the SIM/training joint convention; set_joint_targets_deg maps them to
# physical servos via SIM_TO_PIDOG_SERVO/SERVO_SIGN. VERIFY with --stand on hardware.
ENV_STAND_DEG = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)  # training STAND
GAIT_LIFT = 30.0
GAIT_SWING = 10.0
RESIDUAL_DEG = 12.0

def scripted_trot_deg(phase):
    """Phase-driven symmetric diagonal trot target (sim convention) — matches pidog_env."""
    s = ENV_STAND_DEG; L = GAIT_LIFT; S = GAIT_SWING
    if np.sin(phase) >= 0:   # frame A: LF+RH stance, RF+LH swing
        return np.array([s[0]-S, s[1], s[2]-S, s[3]-L, s[4]+S, s[5]+L, s[6]+S, s[7]])
    return np.array([s[0]+S, s[1]+L, s[2]+S, s[3], s[4]-S, s[5], s[6]-S, s[7]-L])

# ===== PiDog servo mapping =====
# PiDog has 12 servos (3 per leg: shoulder, upper, lower) but the sim uses 2
# per leg (hip + knee). You MUST map sim's 8 joints onto PiDog's servos.
# FILL THIS IN with the correct indices for your PiDog build.
#
# Example mapping (VERIFY BEFORE RUNNING):
#   sim joint 0 (LF_hip)  -> PiDog servo index 1 (left-front upper)
#   sim joint 1 (LF_knee) -> PiDog servo index 2 (left-front lower)
#   ...
SIM_TO_PIDOG_SERVO = {
    0: 1,  1: 2,   # LF hip, knee
    2: 4,  3: 5,   # RF hip, knee
    4: 7,  5: 8,   # LH hip, knee
    6: 10, 7: 11,  # RH hip, knee
}
# Some servos may be mechanically reversed — set to -1 to invert angle.
SERVO_SIGN = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1}


class PolicyMLP:
    """Pure-numpy forward pass of the trained SB3 policy (Tanh activations)."""

    def __init__(self, npz_path):
        w = np.load(npz_path)
        self.w0, self.b0 = w['mlp_0_w'], w['mlp_0_b']
        self.w2, self.b2 = w['mlp_2_w'], w['mlp_2_b']
        self.wa, self.ba = w['action_w'], w['action_b']

    def __call__(self, obs):
        x = np.tanh(self.w0 @ obs + self.b0)
        x = np.tanh(self.w2 @ x + self.b2)
        return self.wa @ x + self.ba  # deterministic mean action


class PiDogInterface:
    """Wraps SunFounder pidog library for read/write.

    Replace stubs with real library calls once verified on hardware.
    """

    def __init__(self):
        from pidog import Pidog
        self.dog = Pidog()
        self.dog.do_action('stand', speed=60)
        time.sleep(1.0)
        self._last_joint_rad = self._read_joint_angles_rad()
        self._last_read_t = time.time()

    def _read_joint_angles_rad(self):
        """Return 8-dim array of current joint angles in radians (sim order)."""
        # pidog.Pidog has .legs.servo_angles (12-element) - map to 8.
        pidog_angles_deg = np.array(self.dog.legs.servo_angles, dtype=np.float64)
        out = np.zeros(8)
        for sim_i, pidog_i in SIM_TO_PIDOG_SERVO.items():
            out[sim_i] = SERVO_SIGN[sim_i] * pidog_angles_deg[pidog_i]
        return np.radians(out)

    def read_imu(self):
        """Return (quat_wxyz, gyro_xyz_rad_s)."""
        # pidog.Pidog exposes .imu.read() — returns dict with accel/gyro.
        # Quaternion may require integrating gyro or using a complementary filter;
        # if unavailable, fall back to zero-roll quat [1,0,0,0].
        imu = self.dog.imu
        # Most SunFounder examples give accel[3], gyro[3]. Use accel for tilt,
        # gyro for angular vel. For obs, synthesize quat from accel-based tilt.
        gyro = np.array(imu.gyro, dtype=np.float64) * (np.pi / 180.0)  # deg/s -> rad/s
        accel = np.array(imu.accel, dtype=np.float64)
        quat = _quat_from_accel(accel)
        return quat, gyro

    def read_joints(self):
        """Return (joint_pos_rad, joint_vel_rad_s) - 8-dim each."""
        now = time.time()
        cur = self._read_joint_angles_rad()
        dt = max(now - self._last_read_t, 1e-3)
        vel = (cur - self._last_joint_rad) / dt
        self._last_joint_rad = cur
        self._last_read_t = now
        return cur, vel

    def set_joint_targets_deg(self, targets_deg):
        """Write 8 joint targets (sim order, degrees) to PiDog servos."""
        angles = list(self.dog.legs.servo_angles)  # 12-element
        for sim_i, pidog_i in SIM_TO_PIDOG_SERVO.items():
            angles[pidog_i] = float(SERVO_SIGN[sim_i] * targets_deg[sim_i])
        self.dog.legs.servo_move(angles, speed=100)

    def stop(self):
        self.dog.do_action('sit', speed=60)
        time.sleep(0.5)
        self.dog.close()


def _quat_from_accel(accel):
    """Approximate orientation quat [w,x,y,z] from accelerometer (tilt only).

    Assumes quasi-static motion. Heading (yaw) is unobservable, set to 0.
    """
    g = accel / (np.linalg.norm(accel) + 1e-6)
    # Angle between body-down (-Z) and gravity
    down = np.array([0, 0, -1.0])
    dot = np.clip(np.dot(down, g), -1.0, 1.0)
    angle = np.arccos(dot)
    if angle < 1e-4:
        return np.array([1.0, 0.0, 0.0, 0.0])
    axis = np.cross(down, g)
    axis /= (np.linalg.norm(axis) + 1e-6)
    w = np.cos(angle / 2)
    xyz = axis * np.sin(angle / 2)
    return np.array([w, xyz[0], xyz[1], xyz[2]])


def build_obs(joint_pos_rad, joint_vel_rad, quat, gyro, gait_phase):
    joint_pos_norm = np.degrees(joint_pos_rad) / 45.0
    joint_vel_norm = joint_vel_rad / 10.0
    torso_vel = np.zeros(3)                  # no sensor
    torso_z = np.array([1.0])                # assume standing height
    gait_clock = np.array([np.sin(gait_phase), np.cos(gait_phase)])
    return np.concatenate([
        joint_pos_norm, joint_vel_norm, quat, torso_vel, gyro, torso_z, gait_clock
    ]).astype(np.float32)


def run(args):
    print(f"Loading policy from {args.model}")
    policy = PolicyMLP(args.model)

    print("Connecting to PiDog...")
    dog = PiDogInterface()

    if args.stand:
        print("Standing test — holding STAND_DEG for 5s")
        dog.set_joint_targets_deg(STAND_DEG)
        time.sleep(5.0)
        dog.stop()
        return

    print(f"Starting policy loop ({args.steps} steps @ 50Hz)")
    last_ctrl_deg = STAND_DEG.copy()
    gait_phase = 0.0

    try:
        for step in range(args.steps):
            t0 = time.time()

            joint_pos, joint_vel = dog.read_joints()
            quat, gyro = dog.read_imu()
            obs = build_obs(joint_pos, joint_vel, quat, gyro, gait_phase)

            raw_action = policy(obs)
            action = np.clip(raw_action, -1.0, 1.0)

            # Residual control: scripted symmetric trot + small learned residual
            target_deg = scripted_trot_deg(gait_phase) + action * RESIDUAL_DEG
            ctrl_deg = SMOOTHING_ALPHA * last_ctrl_deg + (1 - SMOOTHING_ALPHA) * target_deg
            dog.set_joint_targets_deg(ctrl_deg)
            last_ctrl_deg = ctrl_deg

            gait_phase = (gait_phase + 2 * np.pi / GAIT_PERIOD_STEPS) % (2 * np.pi)

            if step % 50 == 0:
                print(f"  step {step:4d} | action_mean={action.mean():+.2f} | "
                      f"obs[0:4]={obs[0:4].round(2)} | loop_ms={(time.time()-t0)*1000:.1f}")

            # Pace to 50 Hz
            elapsed = time.time() - t0
            if elapsed < DT:
                time.sleep(DT - elapsed)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        print("Stopping...")
        dog.stop()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="policy_800k.npz",
                   help="Path to extracted policy .npz")
    p.add_argument("--steps", type=int, default=500,
                   help="Number of 50Hz steps to run (default 500 = 10s)")
    p.add_argument("--stand", action="store_true",
                   help="Standing test only — hold STAND_DEG for 5s, no policy")
    run(p.parse_args())
