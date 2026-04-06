#!/usr/bin/env python3
"""Pretrain PPO policy via behavioral cloning from the scripted trot gait.

Generates (observation, action) pairs by running the sim_trot gait through
PiDogEnv, then trains the policy network with supervised learning (MSE loss).
The pretrained weights are loaded into SB3 PPO for fine-tuning with RL.

Usage:
    python pretrain_bc.py                    # Pretrain and save
    python pretrain_bc.py --eval             # Evaluate pretrained policy
    python pretrain_bc.py --finetune=500000  # Pretrain then PPO fine-tune
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

# Trot gait parameters (from sim_trot.py)
STAND_DEG = np.array([25, 35, -25, -35, 35, 35, -35, -35], dtype=np.float64)
ACTION_RANGE = 15.0
LIFT = 12
SWING = 12


def make_gait_frames():
    """Build the 4-frame diagonal trot pattern (from sim_trot.py)."""
    s = STAND_DEG.copy()

    f1 = s.copy()
    f1[0] = s[0] - LIFT;  f1[1] = s[1] - LIFT
    f1[6] = s[6] + LIFT;  f1[7] = s[7] + LIFT

    f2 = s.copy()
    f2[0] = s[0] + SWING; f2[6] = s[6] - SWING
    f2[2] = s[2] - SWING; f2[4] = s[4] - SWING

    f3 = s.copy()
    f3[2] = s[2] + LIFT;  f3[3] = s[3] + LIFT
    f3[4] = s[4] - LIFT;  f3[5] = s[5] - LIFT

    f4 = s.copy()
    f4[2] = s[2] - SWING; f4[4] = s[4] + SWING
    f4[0] = s[0] - SWING; f4[6] = s[6] + SWING

    return [f1, f2, f3, f4]


def gait_frame_to_action(frame_deg):
    """Convert absolute joint angles (degrees) to normalized [-1, 1] env action."""
    action = (frame_deg - STAND_DEG) / ACTION_RANGE
    return np.clip(action, -1.0, 1.0).astype(np.float32)


def collect_expert_data(n_episodes=30):
    """Run the scripted trot through PiDogEnv and collect (obs, action) pairs.

    Each gait frame is held for 1 agent step (= 15 inner physics steps with
    frame_skip=15, matching the 300ms frame hold in sim_trot.py).
    """
    from pidog_env import PiDogEnv

    env = PiDogEnv()
    gait_frames = make_gait_frames()
    actions = [gait_frame_to_action(f) for f in gait_frames]

    all_obs = []
    all_actions = []

    for ep in range(n_episodes):
        obs, _ = env.reset()

        # Run 16 gait cycles (4 frames each = 64 agent decisions)
        for cycle in range(16):
            for frame_idx in range(4):
                action = actions[frame_idx]
                all_obs.append(obs.copy())
                all_actions.append(action.copy())

                obs, reward, terminated, truncated, _ = env.step(action)
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

    # Create PPO with same architecture as train.py (single env is fine for BC)
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
        n_steps=128, batch_size=64, n_epochs=10,
        learning_rate=3e-4, ent_coef=0.05,
        device=device,
    )
    env.close()

    policy = model.policy
    policy.train()

    # Print expert action statistics
    print(f"  Expert actions — mean: {act_data.mean(axis=0).round(3)}")
    print(f"  Expert actions — std:  {act_data.std(axis=0).round(3)}")
    unique_actions = np.unique(act_data, axis=0)
    print(f"  Unique expert actions: {len(unique_actions)}")

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
            # Forward pass through actor only
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
        if (epoch + 1) % 50 == 0 or epoch == 0:
            # Check what the policy actually predicts for a sample
            with torch.no_grad():
                sample_obs = obs_tensor[:4]
                feats = policy.extract_features(sample_obs, policy.pi_features_extractor)
                lat = policy.mlp_extractor.forward_actor(feats)
                pred = policy.action_net(lat)
            print(f"  Epoch {epoch+1}/{epochs}: loss={avg_loss:.6f}")
            print(f"    Predicted: {pred[0].cpu().numpy().round(3)}")
            print(f"    Expert:    {act_tensor[0].cpu().numpy().round(3)}")

    # Save the pretrained model
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
    # Restore training hyperparameters
    model.ent_coef = 0.02  # lower than initial — policy is already near the trot
    model.learning_rate = 1e-4  # smaller LR for fine-tuning

    print(f"Fine-tuning PPO for {timesteps} steps from pretrained policy...")
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
    obs_data, act_data = collect_expert_data(n_episodes=30)

    # Step 2: Pretrain
    print("\n=== Pretraining policy via behavioral cloning ===")
    model = pretrain_policy(obs_data, act_data, epochs=300, lr=1e-3)

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
