"""Regression guard for the deploy path: the pure-numpy PolicyMLP the robot runs must
reproduce the trained SB3 policy, and deploy's action clip must match training's.

Why this exists
---------------
`eval_mvp.py` validates an SB3 `.zip` policy (run15: 432 mm forward). But the robot does NOT
run that zip -- `deploy_pidog.py:PolicyMLP` is a hand-written numpy forward pass fed by
`extract_weights.py`'s `.npz`. If PolicyMLP or the extraction ever drifts from the SB3 policy,
the robot silently runs a DIFFERENT controller than the one that was validated. Nothing caught
that before this test.

Two properties are pinned, both on IN-DISTRIBUTION observations from a real rollout (random
N(0,1) obs are out of distribution and drive the unbounded Gaussian mean to ~50, which is
meaningless):
  1. faithfulness -- PolicyMLP(obs) == SB3 raw mean action, within float32 precision.
  2. clip parity  -- np.clip(PolicyMLP(obs), -1, 1) == model.predict(obs, deterministic=True).
     deploy_pidog.py line 209 clips to [-1, 1]; SB3.predict clips to the same Box. If these ever
     diverge, the servos get commands eval never saw (gear-strip risk).

Self-contained: builds a fresh in-memory PPO with the canonical policy arch. Extraction
faithfulness is independent of the weights being *good*, so NO training is needed -- this runs
in a few seconds.
"""
import os
import sys

import numpy as np
import pytest

torch = pytest.importorskip("torch")
sb3 = pytest.importorskip("stable_baselines3")
from stable_baselines3 import PPO

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)   # pidog_env.py (canonical 29-dim residual env)
sys.path.insert(0, HERE)   # deploy_pidog.py

import pidog_env                        # noqa: E402
from pidog_env import PiDogEnv          # noqa: E402
import deploy_pidog                     # noqa: E402


CANONICAL_POLICY_KWARGS = dict(
    net_arch=dict(pi=[256, 128], vf=[256, 128]),
    activation_fn=torch.nn.Tanh,
)


def _build_model(seed=0):
    env = PiDogEnv()
    return PPO("MlpPolicy", env, policy_kwargs=CANONICAL_POLICY_KWARGS,
               seed=seed, device="cpu", verbose=0), env


def _extract_npz(model, path):
    """Mirror extract_weights.py exactly."""
    sd = model.policy.state_dict()
    W = lambda k: sd[k].cpu().numpy()
    np.savez(
        path,
        mlp_0_w=W("mlp_extractor.policy_net.0.weight"), mlp_0_b=W("mlp_extractor.policy_net.0.bias"),
        mlp_2_w=W("mlp_extractor.policy_net.2.weight"), mlp_2_b=W("mlp_extractor.policy_net.2.bias"),
        action_w=W("action_net.weight"), action_b=W("action_net.bias"),
    )


def _sb3_raw_mean(model, obs):
    with torch.no_grad():
        dist = model.policy.get_distribution(torch.as_tensor(obs[None]).float())
        return dist.distribution.mean.cpu().numpy()[0]


def _rollout_obs(model, env, n):
    """In-distribution observations: step the env with the (clipped) policy action."""
    obs, _ = env.reset(seed=0)
    out = []
    for _ in range(n):
        out.append(obs.copy())
        raw = _sb3_raw_mean(model, obs)
        obs, _, term, trunc, _ = env.step(np.clip(raw, -1, 1).astype(np.float32))
        if term or trunc:
            obs, _ = env.reset()
    return out


def test_policymlp_matches_sb3_raw_mean(tmp_path):
    model, env = _build_model()
    npz = str(tmp_path / "p.npz")
    _extract_npz(model, npz)
    policy = deploy_pidog.PolicyMLP(npz)

    max_err = max(
        float(np.max(np.abs(policy(obs) - _sb3_raw_mean(model, obs))))
        for obs in _rollout_obs(model, env, 300)
    )
    assert max_err < 1e-4, f"deploy PolicyMLP diverges from SB3 policy by {max_err:.2e}"


def test_deploy_clip_matches_sb3_predict(tmp_path):
    model, env = _build_model()
    npz = str(tmp_path / "p.npz")
    _extract_npz(model, npz)
    policy = deploy_pidog.PolicyMLP(npz)

    for obs in _rollout_obs(model, env, 300):
        deploy_action = np.clip(policy(obs), -1.0, 1.0)   # deploy_pidog.py:209
        sb3_action, _ = model.predict(obs, deterministic=True)
        assert np.allclose(deploy_action, sb3_action, atol=1e-4), (
            "deploy clip diverges from SB3.predict -- servos would get commands eval never saw"
        )


def test_obs_dim_is_29_residual_env():
    """Guards against a regression to the broken 27-dim direct-control env."""
    env = PiDogEnv()
    assert env.observation_space.shape == (29,), (
        f"expected 29-dim residual obs, got {env.observation_space.shape} "
        "-- did the direct-control env leak back to the root?"
    )


def test_deploy_scripted_base_gait_matches_env():
    """The base gait the residual policy rides on is duplicated: env._scripted_trot_deg()
    and deploy_pidog.scripted_trot_deg(). They MUST stay identical -- if either drifts, the
    deployed policy operates around a different base pose than it trained on. Also pins the
    three gait constants (a mismatch there is the same failure by another route)."""
    for c in ("GAIT_LIFT", "GAIT_SWING", "RESIDUAL_DEG"):
        assert getattr(pidog_env, c) == getattr(deploy_pidog, c), f"{c} differs env vs deploy"

    env = PiDogEnv()
    max_err = 0.0
    for phase in np.linspace(0, 4 * np.pi, 400):
        env._phase = phase
        env_base = np.asarray(env._scripted_trot_deg(), float)
        dep_base = np.asarray(deploy_pidog.scripted_trot_deg(phase), float)
        max_err = max(max_err, float(np.max(np.abs(env_base - dep_base))))
    assert max_err < 1e-9, f"deploy scripted base gait drifted from env by {max_err:.2e}"


# ---- servo-map config loading (2026-10: map is csv-driven, fail-closed) ----

def test_servo_map_loaded_from_csv_matches_verified_wiring():
    """Pins the csv-loaded map to the 2026-10 user-verified wiggle test:
    legs pins [2,3,7,8,1,0,10,11] in legs-index order (LH pair swapped at HAT),
    sim->legs mapping the identity permutation, and SERVO_SIGN identity
    (the pidog lib's legs_move owns leg_directions — a deploy-side sign
    would double-invert)."""
    sim_to_legs, sign, legs_to_pin = deploy_pidog.load_servo_map()
    assert sim_to_legs == {i: i for i in range(8)}
    assert all(v == 1 for v in sign.values())
    pins = [legs_to_pin[i] for i in range(8)]
    assert pins == [2, 3, 7, 8, 1, 0, 10, 11], (
        f"legs pins {pins} diverge from the user-verified wiring map"
    )


def test_servo_map_missing_csv_refuses(tmp_path):
    """Fail closed: no csv -> SystemExit, never a silent hardcoded default."""
    with pytest.raises(SystemExit):
        deploy_pidog.load_servo_map(str(tmp_path / "absent.csv"))


def test_servo_map_malformed_csv_refuses(tmp_path):
    """Fail closed on a csv that lost a leg joint."""
    bad = tmp_path / "joint_mapping.csv"
    bad.write_text(
        "body_part,index,pin,joint_name,neutral_angle,direction_positive,min_safe,max_safe,notes\n"
        "legs,0,2,LF_upper,0,shoulder forward,-45,45,\n"
    )
    with pytest.raises(SystemExit):
        deploy_pidog.load_servo_map(str(bad))
