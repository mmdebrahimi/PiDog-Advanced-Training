#!/usr/bin/env python3
"""Train PPO locomotion policy for PiDog in MuJoCo.

Usage:
    python3 train.py                        # Train 100k steps (quick test)
    python3 train.py --timesteps=1000000    # Full training (~30min on laptop)
    python3 train.py --eval                 # Evaluate saved model
    python3 train.py --render               # Render video of trained policy
"""

import argparse
import os
import numpy as np

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(MODEL_DIR, "pidog_policy")


def make_env():
    from pidog_env import PiDogEnv
    return PiDogEnv()


def train(timesteps=100_000, save_path=POLICY_PATH):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import EvalCallback

    env = make_env()

    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        learning_rate=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        device="cpu",
    )

    print(f"Training PPO for {timesteps} timesteps...")
    model.learn(total_timesteps=timesteps)
    model.save(save_path)
    print(f"Model saved to {save_path}")

    env.close()
    return model


def evaluate(model_path=POLICY_PATH, episodes=10):
    from stable_baselines3 import PPO

    env = make_env()
    model = PPO.load(model_path, env=env, device="cpu")

    rewards = []
    steps_list = []

    for ep in range(episodes):
        obs, _ = env.reset()
        total_reward = 0
        steps = 0

        while True:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break

        rewards.append(total_reward)
        steps_list.append(steps)
        forward = env.data.qpos[0]
        print(f"  Episode {ep+1}: reward={total_reward:.2f}, "
              f"steps={steps}, forward={forward*1000:.0f}mm")

    print(f"\nMean reward: {np.mean(rewards):.2f} ± {np.std(rewards):.2f}")
    print(f"Mean steps:  {np.mean(steps_list):.0f}")
    env.close()


def render_video(model_path=POLICY_PATH, output_path=None):
    from stable_baselines3 import PPO
    import mujoco

    if output_path is None:
        output_path = os.path.join(MODEL_DIR, "trained_policy.mp4")

    env = make_env()
    model = PPO.load(model_path, env=env, device="cpu")

    renderer = mujoco.Renderer(env.model, height=480, width=640)
    frames = []

    obs, _ = env.reset()
    for _ in range(500):  # 10 seconds at 50Hz
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, _ = env.step(action)

        renderer.update_scene(env.data)
        frames.append(renderer.render().copy())

        if terminated or truncated:
            break

    forward = env.data.qpos[0]
    print(f"Forward distance: {forward*1000:.0f}mm")

    try:
        import mediapy as media
        media.write_video(output_path, frames, fps=25)
        print(f"Video saved: {output_path} ({len(frames)} frames)")
    except ImportError:
        npz_path = output_path.replace(".mp4", ".npz")
        np.savez_compressed(npz_path, frames=np.array(frames))
        print(f"Frames saved: {npz_path}")

    env.close()


def main():
    parser = argparse.ArgumentParser(description="PiDog PPO training")
    parser.add_argument("--timesteps", type=int, default=100_000,
                        help="Training timesteps (default: 100k)")
    parser.add_argument("--eval", action="store_true",
                        help="Evaluate saved model")
    parser.add_argument("--render", action="store_true",
                        help="Render video of trained policy")
    parser.add_argument("--model", default=POLICY_PATH,
                        help="Model path for eval/render")
    args = parser.parse_args()

    if args.eval:
        evaluate(args.model)
    elif args.render:
        render_video(args.model)
    else:
        train(args.timesteps)


if __name__ == "__main__":
    main()
