#!/usr/bin/env python3
"""Warm-start fine-tune: continue a trained policy under the (modified) reward.

Loads an existing PPO trot policy and continues training with the current env
reward (e.g. + a mild heading term) at a LOWER learning rate / entropy, so the
hard-won gait is preserved and only gently corrected — far cheaper and more
stable than retraining from scratch.

Usage: python train_warmstart.py <src_model.zip> [timesteps]
Saves to the standard POLICY_PATH (pidog_policy).
"""
import os
import sys
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import SubprocVecEnv
from stable_baselines3.common.callbacks import CheckpointCallback
from train import make_env_fn, MODEL_DIR, POLICY_PATH

SRC = sys.argv[1] if len(sys.argv) > 1 else "pidog_policy_run5_gaitclock_trot_CRAB"
STEPS = int(sys.argv[2]) if len(sys.argv) > 2 else 1_500_000

if __name__ == "__main__":
    n_envs = 4   # reduced 8->4: disk/mem pressure on this host (run14 disk-full crash)
    env = SubprocVecEnv([make_env_fn() for _ in range(n_envs)])
    # Lower LR + entropy for gentle fine-tuning (avoid forgetting the trot)
    model = PPO.load(SRC, env=env, device="cpu",
                     custom_objects={"learning_rate": 1e-4, "ent_coef": 0.01})
    print(f"Warm-start from {SRC}: fine-tuning {STEPS} steps at lr=1e-4 ent=0.01")
    ckpt_dir = os.path.join(MODEL_DIR, "checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    cb = CheckpointCallback(save_freq=max(250_000 // n_envs, 1),
                            save_path=ckpt_dir, name_prefix="pidog_ws")
    model.learn(total_timesteps=STEPS, callback=cb, reset_num_timesteps=False)
    model.save(POLICY_PATH)
    print(f"Saved to {POLICY_PATH}")
    env.close()
