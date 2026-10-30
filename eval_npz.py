#!/usr/bin/env python3
"""MVP gate for EXTRACTED (.npz) policies — the artifact the robot actually runs.

Same bar and episode protocol as eval_mvp.py (fwd>=200mm, steps>=800, fwd>|lateral|),
but drives the env with deploy_pidog.PolicyMLP instead of an SB3 .zip, because the
SB3 checkpoints are not committed — only the extracted deploy/*.npz weights are.
Clip parity with deploy (np.clip(action, -1, 1)) is pinned by test_deploy_parity.py.

Usage: python eval_npz.py <policy.npz> [n_episodes]
       python eval_npz.py --report [n_episodes]   # all deploy/policy_*.npz, table + exit 0
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy"))
from deploy_pidog import PolicyMLP  # noqa: E402
from pidog_env import PiDogEnv      # noqa: E402

FWD_MIN, STEP_MIN = 200.0, 800.0


def run_episodes(npz_path, n):
    policy = PolicyMLP(npz_path)
    fwds, lats, steps_list = [], [], []
    for _ in range(n):
        env = PiDogEnv()
        obs, _ = env.reset()
        x0, y0 = float(env.data.qpos[0]), float(env.data.qpos[1])
        steps = 0
        for _ in range(1000):
            a = np.clip(policy(obs), -1.0, 1.0)
            obs, r, term, trunc, _ = env.step(a)
            steps += 1
            if term or trunc:
                break
        fwds.append((float(env.data.qpos[0]) - x0) * 1000.0)
        lats.append(abs(float(env.data.qpos[1]) - y0) * 1000.0)
        steps_list.append(steps)
    return float(np.mean(fwds)), float(np.mean(lats)), float(np.mean(steps_list))


def verdict(mf, ml, ms):
    return (mf >= FWD_MIN) and (ms >= STEP_MIN) and (mf > ml)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        paths = sorted(glob.glob(os.path.join("deploy", "policy_*.npz")))
        print(f"{'policy':34} {'fwd_mm':>8} {'lat_mm':>8} {'steps':>6}  MVP")
        for p in paths:
            mf, ml, ms = run_episodes(p, n)
            print(f"{os.path.basename(p):34} {mf:8.0f} {ml:8.0f} {ms:6.0f}  "
                  f"{'PASS' if verdict(mf, ml, ms) else 'FAIL'}")
        sys.exit(0)

    npz = sys.argv[1] if len(sys.argv) > 1 else "deploy/policy_straight_trot.npz"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    mf, ml, ms = run_episodes(npz, n)
    print(f"MVP-EVAL model={npz} mean_forward_mm={mf:.0f} mean_lateral_mm={ml:.0f} "
          f"mean_steps={ms:.0f} (bar: fwd>={FWD_MIN:.0f}, steps>={STEP_MIN:.0f}, fwd>lat)")
    ok = verdict(mf, ml, ms)
    print("MVP", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
