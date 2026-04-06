#!/usr/bin/env python3
"""Pretrain PPO policy via behavioral cloning from the scripted trot gait.

Generates (observation, action) pairs by running the 2-phase diagonal trot
through PiDogEnv, then trains the policy network with supervised learning.
The pretrained weights are loaded into SB3 PPO for fine-tuning with RL.

Usage:
    python pretrain_bc.py                    # Pretrain and save
    python pretrain_bc.py --eval             # Evaluate pretrained policy
    python pretrain_bc.py --finetune=3000000 # Pretrain then PPO fine-tune
"""

import argparse
import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(MODEL_DIR, "pidog_policy")

# Must match pidog_env.py and sim_trot.py
STAND_DEG = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)
ACTION_RANGE = 15.0
LIFT = 40   # knee bend increase (matches sim_trot.py)
SWING = 20  # hip offset (matches sim_trot.py)
FRAME_HOLD = 10  # env steps per gait frame (200ms at 50Hz)


def make_gait_frames():
    """Build the 2-frame diagonal trot (matches sim_trot.py make_gait_frames)."""
    f1 = np.array([
        STAND_DEG[0] - SWING, STAND_DEG[1],
        STAND_DEG[2] - SWING, STAND_DEG[3] - LIFT,
        STAND_DEG[4] + SWING, STAND_DEG[5] + LIFT,
        STAND_DEG[6] + SWING, STAND_DEG[7],
    ], dtype=np.float64)

    f2 = np.array([
        STAND_DEG[0] + SWING, STAND_DEG[1] + LIFT,
        STAND_DEG[2] + SWING, STAND_DEG[3],
        STAND_DEG[4] - SWING, STAND_DEG[5],
        STAND_DEG[6] - SWING, STAND_DEG[7] - LIFT,
    ], dtype=np.float64)

    return [f1, f2]


def gait_frame_to_action(frame_deg):
    """Convert absolute joint angles (degrees) to normalized [-1, 1] env action."""
    action = (frame_deg - STAND_DEG) / ACTION_RANGE
    return np.clip(action, -1.0, 1.0).astype(np.float32)


def collect_expert_data(n_episodes=20, cycles_per_episode=5):
    """Run the scripted trot through PiDogEnv and collect (obs, action) pairs.

    Each gait frame is held for FRAME_HOLD env steps (10 steps = 200ms),
    matching the sim_trot.py timing. The same action is repeated for all
    10 steps within a frame hold — the policy needs to learn this pattern.
    """
    from pidog_env import PiDogEnv

    env = PiDogEnv()
    gait_frames = make_gait_frames()
    actions = [gait_frame_to_action(f) for f in gait_frames]

    all_obs = []
    all_actions = []

    for ep in range(n_episodes):
        obs, _ = env.reset()

        for cycle in range(cycles_per_episode):
            for frame_idx in range(len(gait_frames)):
                action = actions[frame_idx]

                # Hold this gait frame for FRAME_HOLD env steps
                for hold_step in range(FRAME_HOLD):
                    all_obs.append(obs.copy())
                    all_actions.append(action.copy())

                    obs, reward, terminated, truncated, _ = env.step(action)
                    if terminated or truncated:
                        break
                if terminated or truncated:
                    break
            if terminated or truncated:
                break

        forward = env.data.qpos[0]
        print(f"  Episode {ep+1}/{n_episodes}: forward={forward*1000:.0f}mm, "
              f"steps={env._step_count}")

    env.close()

    obs_array = np.array(all_obs)
    act_array = np.array(all_actions)
    print(f"\nCollected {len(obs_array)} expert samples")
    print(f"  Unique actions: {len(np.unique(act_array, axis=0))}")
    print(f"  Actions mean: {act_array.mean(axis=0).round(3)}")
    return obs_array, act_array


def pretrain_policy(obs_data, act_data, epochs=500, lr=3e-3):
    """Train the SB3 PPO actor network to imitate expert actions via MSE loss.

    Only optimizes actor-related parameters (feature extractor + pi layers +
    action_net), NOT the value network or log_std.
    """
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv
    from stable_baselines3.common.monitor import Monitor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    def make_env_fn():
        def _init():
            from pidog_env import PiDogEnv
            return Monitor(PiDogEnv())
        return _init

    env = DummyVecEnv([make_env_fn()])

    policy_kwargs = dict(
        net_arch=dict(pi=[256, 128], vf=[256, 128]),
        activation_fn=torch.nn.Tanh,
    )

    model = PPO(
        "MlpPolicy", env, verbose=0,
        policy_kwargs=policy_kwargs,
        n_steps=1024, batch_size=256, n_epochs=10,
        learning_rate=3e-4, ent_coef=0.01,
        device=device,
    )
    env.close()

    policy = model.policy
    policy.train()

    # Prepare data
    obs_tensor = torch.FloatTensor(obs_data).to(device)
    act_tensor = torch.FloatTensor(act_data).to(device)
    dataset = TensorDataset(obs_tensor, act_tensor)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    # Only optimize actor parameters (not value network or log_std)
    actor_params = (
        list(policy.features_extractor.parameters()) +
        list(policy.mlp_extractor.policy_net.parameters()) +
        list(policy.action_net.parameters())
    )
    optimizer = torch.optim.Adam(actor_params, lr=lr)
    mse_loss = nn.MSELoss()

    for epoch in range(epochs):
        total_loss = 0
        n_batches = 0
        for obs_batch, act_batch in loader:
            features = policy.extract_features(obs_batch, policy.pi_features_extractor)
            latent_pi = policy.mlp_extractor.forward_actor(features)
            action_mean = policy.action_net(latent_pi)

            loss = mse_loss(action_mean, act_batch)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        avg_loss = total_loss / n_batches
        if (epoch + 1) % 100 == 0 or epoch == 0:
            with torch.no_grad():
                sample_obs = obs_tensor[:4]
                feats = policy.extract_features(sample_obs, policy.pi_features_extractor)
                lat = policy.mlp_extractor.forward_actor(feats)
                pred = policy.action_net(lat)
            print(f"  Epoch {epoch+1}/{epochs}: loss={avg_loss:.6f}")
            print(f"    Predicted: {pred[0].cpu().numpy().round(3)}")
            print(f"    Expert:    {act_tensor[0].cpu().numpy().round(3)}")

    model.save(POLICY_PATH)
    print(f"\nPretrained model saved to {POLICY_PATH}")
    return model


def evaluate_pretrained(model_path=POLICY_PATH, episodes=10):
    """Evaluate the BC-pretrained policy."""
    from stable_baselines3 import PPO
    from pidog_env import PiDogEnv

    device = "cuda" if torch.cuda.is_available() else "cpu"
    env = PiDogEnv()
    model = PPO.load(model_path, env=env, device=device)

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

        forward = env.data.qpos[0]
        lateral = env.data.qpos[1]
        print(f"  Episode {ep+1}: reward={total_reward:.2f}, steps={steps}, "
              f"forward={forward*1000:.0f}mm, lateral={lateral*1000:.0f}mm")

    env.close()


def finetune(timesteps, model_path=POLICY_PATH):
    """Load pretrained model and continue training with PPO."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from stable_baselines3.common.monitor import Monitor

    device = "cuda" if torch.cuda.is_available() else "cpu"

    def make_env_fn():
        def _init():
            from pidog_env import PiDogEnv
            return Monitor(PiDogEnv())
        return _init

    n_envs = 8
    env = SubprocVecEnv([make_env_fn() for _ in range(n_envs)])

    model = PPO.load(model_path, env=env, device=device)
    model.ent_coef = 0.02   # lower than scratch — policy already near the trot
    model.learning_rate = 1e-4  # smaller LR for fine-tuning

    print(f"Fine-tuning PPO for {timesteps} steps from pretrained policy...")
    print(f"  ent_coef={model.ent_coef}, lr={model.learning_rate}")
    model.learn(total_timesteps=timesteps)
    model.save(model_path)
    print(f"Fine-tuned model saved to {model_path}")

    env.close()


def main():
    parser = argparse.ArgumentParser(description="PiDog BC pretraining")
    parser.add_argument("--eval", action="store_true", help="Evaluate pretrained model")
    parser.add_argument("--finetune", type=int, default=0,
                        help="PPO fine-tune timesteps after pretraining")
    args = parser.parse_args()

    if args.eval:
        evaluate_pretrained()
        return

    # Step 1: Collect expert data
    print("=== Collecting expert data from scripted trot ===")
    obs_data, act_data = collect_expert_data(n_episodes=20, cycles_per_episode=5)

    # Step 2: Pretrain
    print("\n=== Pretraining policy via behavioral cloning ===")
    model = pretrain_policy(obs_data, act_data, epochs=500, lr=3e-3)

    # Step 3: Evaluate
    print("\n=== Evaluating pretrained policy ===")
    evaluate_pretrained()

    # Step 4: Fine-tune with PPO (optional)
    if args.finetune > 0:
        print(f"\n=== Fine-tuning with PPO for {args.finetune} steps ===")
        finetune(args.finetune)
        print("\n=== Evaluating fine-tuned policy ===")
        evaluate_pretrained()


if __name__ == "__main__":
    main()
