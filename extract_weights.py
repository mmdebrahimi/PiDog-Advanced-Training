#!/usr/bin/env python3
"""Extract an SB3 PPO MlpPolicy into the npz format deploy_pidog.py runs.

The Pi runs a pure-numpy forward pass: tanh(W0 x + b0) -> tanh(W2 . + b2) -> Wa . + ba.
SB3 separate-actor MlpPolicy stores the actor as:
  mlp_extractor.policy_net.0 (Linear in->256), .2 (Linear 256->128), action_net (128->8).

Usage: python extract_weights.py <model.zip> <out.npz>
Verifies the extracted npz reproduces model.predict(deterministic=True) before saving.
"""
import sys
import numpy as np
from stable_baselines3 import PPO

src = sys.argv[1] if len(sys.argv) > 1 else "pidog_policy"
out = sys.argv[2] if len(sys.argv) > 2 else "deploy/policy_new.npz"

model = PPO.load(src, device="cpu")
sd = model.policy.state_dict()

def W(k): return sd[k].cpu().numpy()

weights = dict(
    mlp_0_w=W("mlp_extractor.policy_net.0.weight"), mlp_0_b=W("mlp_extractor.policy_net.0.bias"),
    mlp_2_w=W("mlp_extractor.policy_net.2.weight"), mlp_2_b=W("mlp_extractor.policy_net.2.bias"),
    action_w=W("action_net.weight"), action_b=W("action_net.bias"),
)
for k, v in weights.items():
    print(f"  {k:10} {v.shape}")

# Verify: numpy forward pass == SB3 deterministic mean action, on random obs
obs_dim = weights["mlp_0_w"].shape[1]
def fwd(o):
    x = np.tanh(weights["mlp_0_w"] @ o + weights["mlp_0_b"])
    x = np.tanh(weights["mlp_2_w"] @ x + weights["mlp_2_b"])
    return weights["action_w"] @ x + weights["action_b"]

# SB3 predict() clips to the Box bounds [-1,1]; the deploy clips identically
# (deploy_pidog.py: np.clip(raw_action,-1,1)). So compare CLIPPED forward.
rng = np.random.RandomState(0)
max_err = 0.0
for _ in range(20):
    o = rng.randn(obs_dim).astype(np.float32)
    a_sb3, _ = model.predict(o, deterministic=True)
    max_err = max(max_err, float(np.max(np.abs(np.clip(fwd(o), -1.0, 1.0) - a_sb3))))
print(f"max |clip(numpy) - SB3.predict| over 20 random obs = {max_err:.2e}")
assert max_err < 1e-4, "extraction mismatch -- numpy forward != SB3 policy"

np.savez(out, **weights)
print(f"OK -> saved {out} (obs_dim={obs_dim})")
