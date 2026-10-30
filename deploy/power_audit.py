#!/usr/bin/env python3
"""Offline power-feasibility audit: what will a policy ask of the servo supply?

The robot browns out when too many servos draw inrush current at once (known
points: 8 simultaneous = instant reboot at ~8.0V; sequenced single-leg moves OK
at 7.87V). Servo current scales with commanded step size, so the auditable
sim-side proxy is the per-tick COMMANDED delta each servo receives, measured on
exactly the command stream deploy_pidog.py would issue (scripted base gait +
clipped residual, smoothing alpha 0.8, 50 Hz).

Reported per gait/policy:
  max_simult   - max count of servos whose per-tick |delta| exceeds --move-deg
  worst_sum    - max over ticks of sum|delta| across 8 servos (current proxy, deg/tick)
  p95_sum      - 95th percentile of the tick sum
These are the numbers to line up against the Pi-side brownout step test
(hw_checkup harness): once hardware says "N simultaneous servos safe", any
policy whose max_simult <= N is deployable on the power axis.

Usage:
  python deploy/power_audit.py --all            # staged policies + scripted references
  python deploy/power_audit.py deploy/policy_dr_robust.npz
Options: --steps N (default 1000), --move-deg D (default 0.5), --episodes K (default 3)
"""
import argparse
import glob
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from deploy_pidog import PolicyMLP, scripted_trot_deg, SMOOTHING_ALPHA, RESIDUAL_DEG, GAIT_PERIOD_STEPS  # noqa: E402
from pidog_env import PiDogEnv  # noqa: E402


def scripted_crawl_deg(phase):
    """One-leg-at-a-time crawl reference (stock lib lift order LF,LH,RF,RH shape).

    Power reference only — NOT a trained gait. One quarter of the cycle per leg:
    the swing leg's two joints move through lift+swing, the others hold stance.
    """
    from deploy_pidog import ENV_STAND_DEG, GAIT_LIFT, GAIT_SWING
    s = np.array(ENV_STAND_DEG, dtype=np.float64).copy()
    quarter = (phase % (2 * np.pi)) / (np.pi / 2.0)
    leg = int(quarter) % 4            # 0:LF 1:RF 2:LH 3:RH (sim joint pairs)
    t = quarter - int(quarter)        # 0..1 within the swing
    lift = np.sin(np.pi * t)          # smooth up-down
    hip_i, knee_i = 2 * leg, 2 * leg + 1
    s[hip_i] += GAIT_SWING * np.sin(2 * np.pi * t)
    s[knee_i] += GAIT_LIFT * lift * (1 if s[knee_i] >= 0 else -1)
    return s


def audit_stream(policy, base_gait, steps, move_deg, episodes, use_env):
    """Reproduce deploy's command stream; return (max_simult, worst_sum, p95_sum)."""
    simult, sums = [], []
    for _ in range(episodes):
        env = PiDogEnv() if use_env else None
        obs = env.reset()[0] if env else None
        last_ctrl = base_gait(0.0)
        phase = 0.0
        for _ in range(steps):
            residual = np.zeros(8)
            if policy is not None:
                residual = np.clip(policy(obs), -1.0, 1.0) * RESIDUAL_DEG
            target = base_gait(phase) + residual
            ctrl = SMOOTHING_ALPHA * last_ctrl + (1 - SMOOTHING_ALPHA) * target
            delta = np.abs(ctrl - last_ctrl)
            simult.append(int(np.sum(delta > move_deg)))
            sums.append(float(np.sum(delta)))
            last_ctrl = ctrl
            if env is not None:
                obs, _, term, trunc, _ = env.step(residual / RESIDUAL_DEG)
                if term or trunc:
                    break
            phase = (phase + 2 * np.pi / GAIT_PERIOD_STEPS) % (2 * np.pi)
    return max(simult), max(sums), float(np.percentile(sums, 95))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help=".npz policy path")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--move-deg", type=float, default=0.5)
    ap.add_argument("--episodes", type=int, default=3)
    args = ap.parse_args()

    rows = []
    if args.all or not args.target:
        rows.append(("scripted_trot (no residual)", None, scripted_trot_deg, False))
        rows.append(("scripted_crawl reference", None, scripted_crawl_deg, False))
        for p in sorted(glob.glob(os.path.join(HERE, "policy_*.npz"))):
            name = os.path.basename(p)
            if name in ("policy_800k.npz", "policy_trot29.npz"):
                continue  # pre-residual artifacts, fail the MVP gate, never deploy
            rows.append((name, PolicyMLP(p), scripted_trot_deg, True))
    else:
        rows.append((os.path.basename(args.target), PolicyMLP(args.target), scripted_trot_deg, True))

    print(f"{'gait / policy':38} {'max_simult':>10} {'worst_sum':>10} {'p95_sum':>8}   (move>{args.move_deg} deg/tick)")
    for name, pol, base, use_env in rows:
        ms, ws, p95 = audit_stream(pol, base, args.steps, args.move_deg, args.episodes, use_env)
        print(f"{name:38} {ms:10d} {ws:10.1f} {p95:8.1f}")
    print("\nInterpretation: compare max_simult against the hardware-measured safe "
          "simultaneous-servo count (hw_checkup brownout step test). worst_sum is a "
          "relative current proxy across gaits, not amps.")


if __name__ == "__main__":
    main()
