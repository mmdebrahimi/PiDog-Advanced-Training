#!/usr/bin/env python3
"""Train PPO locomotion policy for PiDog in MuJoCo.

Uses Stable Baselines3 PPO with 8 parallel MuJoCo environments.
The policy network is a 256-128 MLP with Tanh activations for both
actor and critic. CUDA is auto-detected for GPU training.

Usage:
    python train.py                         # Train 100k steps (quick test)
    python train.py --timesteps=3000000     # Full training run
    python train.py --eval                  # Evaluate saved model (10 episodes)
    python train.py --render                # Render video of trained policy

Important: After editing pidog_env.py, delete __pycache__/ before training.
SubprocVecEnv spawns separate processes that may load stale cached bytecode.
"""

import argparse
import os

# Fix CUDA detection on Windows — must be set before torch import.
# See: https://github.com/pytorch/pytorch/issues/... (cudaGetDeviceCount error)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import numpy as np
import torch
from stable_baselines3.common.vec_env import SubprocVecEnv
import mediapy as media

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(MODEL_DIR, "pidog_policy")


def make_env():
    """Create a single PiDogEnv (used for eval/render in the main process)."""
    from pidog_env import PiDogEnv
    return PiDogEnv()


from stable_baselines3.common.monitor import Monitor

def make_env_fn():
    """Factory for SubprocVecEnv — each subprocess gets its own Monitor-wrapped env."""
    def _init():
        from pidog_env import PiDogEnv
        env = PiDogEnv()
        return Monitor(env)
    return _init


def linear_schedule(initial_value: float):
    """Linear LR decay from initial_value → 0 over training. Currently unused."""
    def func(progress_remaining: float) -> float:
        return progress_remaining * initial_value
    return func


def train(timesteps=100_000, save_path=POLICY_PATH):
    """Train PPO policy with 8 parallel environments.

    Key hyperparameters (tuned for quadruped locomotion):
      - n_steps=1024: rollout buffer per env (8192 total samples per update)
      - batch_size=256: minibatch size → 32 gradient steps per epoch
      - ent_coef=0.05: high entropy bonus to prevent premature std collapse
                       (without this, the policy converges to "stand still")
      - learning_rate=3e-4: constant (linear decay caused policy to stop learning)
      - net_arch=[256,128]: larger than default 64-64 for 27-dim obs + 8-dim action
    """
    from stable_baselines3 import PPO

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    n_envs = 8
    env = SubprocVecEnv([make_env_fn() for _ in range(n_envs)])

    # Separate actor/critic networks with Tanh (standard for locomotion)
    policy_kwargs = dict(
        net_arch=dict(pi=[256, 128], vf=[256, 128]),
        activation_fn=torch.nn.Tanh,
    )

    model = PPO(
        "MlpPolicy",
        env,
        verbose=1,
        policy_kwargs=policy_kwargs,
        n_steps=1024,           # 1024 steps × 8 envs = 8192 samples per update
        batch_size=256,         # 8192 / 256 = 32 minibatches per epoch
        n_epochs=10,            # 10 passes over the rollout buffer
        learning_rate=3e-4,     # constant LR (linear decay caused premature convergence)
        gamma=0.99,             # discount factor
        gae_lambda=0.95,        # GAE advantage estimation
        clip_range=0.2,         # PPO clipping
        ent_coef=0.05,          # entropy bonus — keeps exploration alive
        device=device,
    )

    print(f"Training PPO for {timesteps} timesteps with {n_envs} parallel envs...")
    model.learn(total_timesteps=timesteps)
    model.save(save_path)
    print(f"Model saved to {save_path}")

    env.close()
    return model


def evaluate(model_path=POLICY_PATH, episodes=10):
    """Run deterministic policy for N episodes and report metrics."""
    from stable_baselines3 import PPO

    device = "cuda" if torch.cuda.is_available() else "cpu"
    env = make_env()
    model = PPO.load(model_path, env=env, device=device)

    rewards = []
    steps_list = []
    forward_list = []
    lateral_list = []

    for ep in range(episodes):
        obs, _ = env.reset()
        total_reward = 0.0
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
        lateral = env.data.qpos[1]
        forward_list.append(forward)
        lateral_list.append(lateral)

        print(
            f"  Episode {ep+1}: reward={total_reward:.2f}, "
            f"steps={steps}, forward={forward*1000:.0f}mm, lateral={lateral*1000:.0f}mm"
        )

    print(f"\nMean reward:   {np.mean(rewards):.2f} ± {np.std(rewards):.2f}")
    print(f"Mean steps:    {np.mean(steps_list):.0f}")
    print(f"Mean forward:  {np.mean(forward_list)*1000:.1f} mm")
    print(f"Mean lateral:  {np.mean(lateral_list)*1000:.1f} mm")

    env.close()


def render_video(model_path=POLICY_PATH, output_path=None):
    """Render trained policy to MP4 video (500 frames ≈ 10s at 50Hz control rate)."""
    from stable_baselines3 import PPO
    import mujoco

    if output_path is None:
        output_path = os.path.join(MODEL_DIR, "trained_policy.mp4")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    env = make_env()
    model = PPO.load(model_path, env=env, device=device)

    renderer = mujoco.Renderer(env.model, height=480, width=640)
    frames = []

    obs, _ = env.reset()
    for _ in range(500):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, _ = env.step(action)

        renderer.update_scene(env.data)
        frames.append(renderer.render().copy())

        if terminated or truncated:
            break

    forward = env.data.qpos[0]
    lateral = env.data.qpos[1]
    print(f"Forward distance: {forward*1000:.0f}mm")
    print(f"Lateral drift:    {lateral*1000:.0f}mm")

    try:

        ffmpeg_bin = r"C:\Users\b0652085\Downloads\Software Downloaded\ffmpeg-8.1-essentials_build\bin"
        os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")

        media.write_video(output_path, frames, fps=25)
        print(f"Video saved: {output_path} ({len(frames)} frames)")
    except ImportError:
        npz_path = output_path.replace(".mp4", ".npz")
        np.savez_compressed(npz_path, frames=np.array(frames))
        print(f"Frames saved: {npz_path}")

    env.close()


def main():
    parser = argparse.ArgumentParser(description="PiDog PPO training")
    parser.add_argument(
        "--timesteps",
        type=int,
        default=100_000,
        help="Training timesteps (default: 100k)"
    )
    parser.add_argument("--eval", action="store_true", help="Evaluate saved model")
    parser.add_argument("--render", action="store_true", help="Render video of trained policy")
    parser.add_argument("--model", default=POLICY_PATH, help="Model path for eval/render")
    args = parser.parse_args()

    if args.eval:
        evaluate(args.model)
    elif args.render:
        render_video(args.model)
    else:
        train(args.timesteps)


if __name__ == "__main__":
    main()
