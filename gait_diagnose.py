#!/usr/bin/env python3
"""Per-leg gait diagnosis for the PiDog walking policy.

Goes beyond forward/lateral/steps: reads the 4 foot-site z-heights every step to
recover per-leg duty %, swing/lift, and the diagonal-trot phase signature  the
observability needed to tell a TRUE TROT from a SCOOTER (both have forward>0).

Emits a signal vector + a priority-ordered failure-mode verdict + the single
recommended lever, matching the diagnosis decision tree.

Usage: python gait_diagnose.py [model_path] [n_episodes]
Exit 0 iff verdict == TRUE_TROT (MVP), else 1.
"""
import sys
import numpy as np
import mujoco
from stable_baselines3 import PPO
from pidog_env import PiDogEnv

MODEL = sys.argv[1] if len(sys.argv) > 1 else "pidog_policy"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
FEET = ["lf_foot", "rf_foot", "lh_foot", "rh_foot"]
CONTACT_Z = 0.012   # foot considered "down" below 12mm (toe radius 10mm + margin)
SWING_Z = 0.018     # leg "active" if it lifts above 18mm at some point
FWD_MIN, STEP_MIN = 200.0, 800.0

def yaw_of(q):
    w, x, y, z = q
    return float(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

def wrap_deg(rad):
    d = np.degrees(rad)
    return (d + 180) % 360 - 180  # wrap to [-180, 180]

model = PPO.load(MODEL, device="cpu")
env = PiDogEnv()
foot_ids = [mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_SITE, f) for f in FEET]

E_fwd, E_lat, E_steps, E_zmean, E_zstd, E_vert, E_jit, E_yaw = [], [], [], [], [], [], [], []
duty = np.zeros(4); lift = np.zeros(4); contacts_all = [[] for _ in range(4)]
n_terms = 0

for ep in range(N):
    obs, _ = env.reset()
    x0, y0 = float(env.data.qpos[0]), float(env.data.qpos[1])
    yaw0 = yaw_of(env.data.qpos[3:7].copy())
    zs, verts, jit = [], [], []
    last_a = np.zeros(env.action_space.shape)
    ep_contacts = [[] for _ in range(4)]
    steps = 0
    for _ in range(1000):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, _ = env.step(a)
        steps += 1
        for i, fid in enumerate(foot_ids):
            z = float(env.data.site_xpos[fid][2])
            down = z < CONTACT_Z
            ep_contacts[i].append(down)
            duty[i] += down
            lift[i] = max(lift[i], z)
        zs.append(float(env.data.qpos[2]))
        verts.append(abs(float(env.data.qvel[2])))
        jit.append(float(np.sum((a - last_a) ** 2))); last_a = a
        if term or trunc:
            n_terms += 1 if term else 0
            break
    E_fwd.append((float(env.data.qpos[0]) - x0) * 1000)
    E_lat.append(abs(float(env.data.qpos[1]) - y0) * 1000)
    E_steps.append(steps); E_zmean.append(np.mean(zs) * 1000); E_zstd.append(np.std(zs) * 1000)
    E_vert.append(np.sqrt(np.mean(np.square(verts)))); E_jit.append(np.mean(jit))
    E_yaw.append(abs(wrap_deg(yaw_of(env.data.qpos[3:7].copy()) - yaw0)))
    for i in range(4):
        contacts_all[i].extend(ep_contacts[i])

tot = sum(len(c) for c in contacts_all) / 4
duty_pct = duty / max(tot, 1)
C = [np.array(c, dtype=float) for c in contacts_all]   # 0/1 per-leg contact streams
def agree(a, b): return float(np.mean(a == b))
LF, RF, LH, RH = 0, 1, 2, 3
diag_sync = 0.5 * (agree(C[LF], C[RH]) + agree(C[RF], C[LH]))
front_alt = float(np.mean(C[LF] != C[RF]))
active = [(lift[i] > SWING_Z) and (duty_pct[i] < 0.95) for i in range(4)]
n_active = sum(active)

mf, ml, ms = np.mean(E_fwd), np.mean(E_lat), np.mean(E_steps)
zmean, zstd, vert, jitm = np.mean(E_zmean), np.mean(E_zstd), np.mean(E_vert), np.mean(E_jit)
ydrift = np.mean(E_yaw)   # mean |final yaw - initial yaw| in degrees

print("=" * 70)
print(f"GAIT DIAGNOSTIC  model={MODEL}  ({N} episodes)")
print(f"  BODY   forward={mf:.0f}mm  lateral={ml:.0f}mm  steps={ms:.0f}/1000  "
      f"torso_z={zmean:.0f}+/-{zstd:.0f}mm  vert_rms={vert:.3f}  jitter={jitm:.3f}  yaw_drift={ydrift:.0f}deg")
print(f"  LEG    " + "  ".join(f"{FEET[i][:2].upper()}:duty{duty_pct[i]*100:.0f}% "
      f"lift{lift[i]*1000:.0f}mm{'*' if active[i] else ' '}" for i in range(4)))
print(f"  PHASE  diag_sync={diag_sync:.2f}  front_alt={front_alt:.2f}  active_legs={n_active}/4")

# Priority-ordered failure-mode decision tree.
# Order: survival -> meaningful direction -> is-it-locomoting -> gait-quality.
# Thresholds: BACKWARD only on MEANINGFUL reverse (<-50mm); |fwd|<50mm = not
# locomoting (= standing/degenerate pose, regardless of leg posture).
if ms < STEP_MIN:
    verdict, lever = "FALLS-EARLY", "+death -50->-80, +orientation 2->4, -forward 30->20"
elif mf < -50:
    verdict, lever = "BACKWARD", "verify qvel[0] sign / clip forward<0"
elif mf < 50:
    verdict, lever = "STANDING/POSE", "+forward, -alive, +ent_coef 0.05->0.08 (not locomoting; leg pose irrelevant)"
elif n_active <= 2 or diag_sync < 0.6:
    verdict, lever = "SCOOTER/EXPLOIT", "ADD gait-clock obs (sin/cos) + diagonal-contact reward + L/R symmetry penalty"
elif vert > 0.15 or zstd > 12:
    verdict, lever = "BOUNCING/HOP", "+vertical penalty + contact schedule"
elif ml > mf and ydrift >= 20:
    verdict, lever = "YAWED-WALK", "heading term: reward fwd-vel proj on initial heading + mild yaw-deviation penalty (body turned, not side-stepping)"
elif ml > mf:
    verdict, lever = "CRABBING", "+body-frame lateral penalty (true side-step, low yaw drift)"
elif zmean < 40:
    verdict, lever = "BELLY-DRAG", "+height penalty"
elif mf >= FWD_MIN and n_active == 4 and diag_sync >= 0.7 and front_alt >= 0.5 and ms >= STEP_MIN and mf > ml:
    verdict, lever = "TRUE_TROT", "PASS -> push to Pi"
else:
    verdict, lever = "WEAK-WALK", "+forward weight slightly / more steps"

passed = verdict == "TRUE_TROT"
print(f"  VERDICT  >>> {verdict} <<<")
print(f"  LEVER    {lever}")
print(f"  MVP      {'PASS' if passed else 'FAIL'}")
print("=" * 70)
sys.exit(0 if passed else 1)
