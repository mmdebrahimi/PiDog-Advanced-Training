"""Checkpointed PPO trainer for PiDog.

Why this exists
---------------
`train.py:train()` calls `model.save()` ONLY after `model.learn()` returns. A 2026-07-08
run reached 1,015,808 steps with ep_rew_mean=527 / ep_len_mean=1000 (both above the
LAPTOP_HANDOFF.md success bar) and was then killed before the final save -- the entire
trained policy was lost.

This script mirrors train.py's hyperparameters EXACTLY (do not diverge -- they are tuned)
and adds:
  * CheckpointCallback  -- periodic saves, so an interrupted run loses <= save_every steps
  * --resume            -- continue from a checkpoint with `set_parameters`
  * final save          -- same artifact path/shape as train.py

Usage:
    python train_ckpt.py --timesteps 1500000 --save-every 50000
    python train_ckpt.py --resume checkpoints/pidog_ckpt_900000_steps.zip --timesteps 600000
"""
import argparse
import math
import os

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import SubprocVecEnv

from train import make_env_fn, POLICY_PATH

CKPT_DIR = "checkpoints"
CKPT_PREFIX = "pidog_ckpt"
N_ENVS = 8


def build_model(env, device, ent_coef=0.01, gamma=0.99):
    """PPO with train.py's exact tuned hyperparameters. Keep in sync.

    ent_coef is parameterized because train.py:64's docstring prescribes 0.05
    ("prevents premature std collapse -> policy converges to 'stand still'")
    while train.py:95 actually passes 0.01. The 0.01 run reproduced exactly the
    collapse the docstring warns about (forward=15.7mm, std 0.97->0.41).
    """
    policy_kwargs = dict(
        net_arch=dict(pi=[256, 128], vf=[256, 128]),
        activation_fn=torch.nn.Tanh,
    )
    return PPO(
        "MlpPolicy",
        env,
        verbose=1,
        policy_kwargs=policy_kwargs,
        n_steps=1024,
        batch_size=256,
        n_epochs=10,
        learning_rate=3e-4,
        gamma=gamma,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=ent_coef,
        device=device,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timesteps", type=int, default=1_500_000)
    ap.add_argument("--save-every", type=int, default=50_000,
                    help="global env steps between checkpoints")
    ap.add_argument("--resume", type=str, default=None,
                    help="path to a checkpoint .zip to continue from")
    ap.add_argument("--save-path", type=str, default=POLICY_PATH)
    ap.add_argument("--ent-coef", type=float, default=0.01,
                    help="0.05 per train.py:64 docstring; 0.01 collapses to stand-still")
    ap.add_argument("--ckpt-prefix", type=str, default=CKPT_PREFIX)
    ap.add_argument("--reset-std", type=float, default=None,
                    help="After --resume, re-inflate the policy's action std. A converged "
                         "stand-still policy has std~0.41 and never SAMPLES a gait, so "
                         "fine-tuning it stays pinned at the standing optimum forever.")
    ap.add_argument("--gamma", type=float, default=0.99,
                    help="0.99 => ~100-step horizon, too short: a forward dive out-values "
                         "a stable 1000-step gait. 0.995 => ~200 steps.")
    args = ap.parse_args()

    os.makedirs(CKPT_DIR, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}", flush=True)

    env = SubprocVecEnv([make_env_fn() for _ in range(N_ENVS)])
    model = build_model(env, device, ent_coef=args.ent_coef, gamma=args.gamma)
    print(f"ent_coef={args.ent_coef} gamma={args.gamma}", flush=True)

    if args.resume:
        print(f"Resuming from {args.resume}", flush=True)
        model.set_parameters(args.resume)
        if args.reset_std is not None:
            with torch.no_grad():
                model.policy.log_std.data.fill_(math.log(args.reset_std))
            print(f"Reset action std -> {args.reset_std}", flush=True)

    # CheckpointCallback counts calls-per-env, so divide by N_ENVS to get global steps.
    save_freq = max(1, args.save_every // N_ENVS)
    ckpt_cb = CheckpointCallback(
        save_freq=save_freq,
        save_path=CKPT_DIR,
        name_prefix=args.ckpt_prefix,
    )

    print(
        f"Training PPO for {args.timesteps} steps, {N_ENVS} envs, "
        f"checkpoint every {args.save_every} steps -> {CKPT_DIR}/",
        flush=True,
    )
    try:
        model.learn(total_timesteps=args.timesteps, callback=ckpt_cb,
                    reset_num_timesteps=not bool(args.resume))
    finally:
        # Save even on KeyboardInterrupt / exception -- never lose a trained policy again.
        model.save(args.save_path)
        print(f"Model saved to {args.save_path}", flush=True)
        env.close()


if __name__ == "__main__":
    main()
