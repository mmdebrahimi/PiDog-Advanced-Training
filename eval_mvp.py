#!/usr/bin/env python3
"""MVP gate for the PiDog walking policy — code-owned checkable predicate.

Runs N deterministic episodes, measures net forward/lateral torso displacement
and survival, and exits 0 iff the MVP bar is met:
  - mean forward >= FWD_MIN mm   (clearly locomoting, not standing ~16mm)
  - mean survived steps >= STEP_MIN   (doesn't fall early)
  - mean forward > mean |lateral|     (goes forward, not sideways/scooting)

Usage: python eval_mvp.py [model_path] [n_episodes]
"""
import sys
import numpy as np
from stable_baselines3 import PPO
from pidog_env import PiDogEnv

MODEL = sys.argv[1] if len(sys.argv) > 1 else "pidog_policy"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10
FWD_MIN, STEP_MIN = 200.0, 800.0

model = PPO.load(MODEL, device="cpu")
fwds, lats, steps_list = [], [], []
for ep in range(N):
    env = PiDogEnv()
    obs, _ = env.reset()
    x0, y0 = float(env.data.qpos[0]), float(env.data.qpos[1])
    steps = 0
    for _ in range(1000):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, _ = env.step(a)
        steps += 1
        if term or trunc:
            break
    fwds.append((float(env.data.qpos[0]) - x0) * 1000.0)
    lats.append(abs(float(env.data.qpos[1]) - y0) * 1000.0)
    steps_list.append(steps)

mf, ml, ms = float(np.mean(fwds)), float(np.mean(lats)), float(np.mean(steps_list))
print(f"MVP-EVAL model={MODEL} mean_forward_mm={mf:.0f} mean_lateral_mm={ml:.0f} "
      f"mean_steps={ms:.0f} (bar: fwd>={FWD_MIN:.0f}, steps>={STEP_MIN:.0f}, fwd>lat)")
ok = (mf >= FWD_MIN) and (ms >= STEP_MIN) and (mf > ml)
print("MVP", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
