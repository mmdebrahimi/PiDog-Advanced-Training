"""Unit tests for eval_npz.py — the MVP gate for EXTRACTED (.npz) policies.

Why this exists
---------------
eval_npz.py is the LAST gate before a policy goes to the robot: it decides
PASS/FAIL for the deploy artifact itself (the .npz), not the SB3 zip. If its
episode accounting or verdict thresholds drift, a policy that never cleared
the bar gets a PASS (robot runs an unvalidated controller) or a good policy
gets blocked. Nothing pinned that logic before this file.

Two layers:
  1. verdict() — pure threshold logic. Pinned directly on hand-picked values
     at and around the bar (fwd>=200, steps>=800, fwd>|lat| — note verdict
     receives the ALREADY-ABS lateral mean, so fwd>lat is the straightness
     test).
  2. run_episodes() — episode loop accounting (m->mm conversion, lateral
     abs(), early termination, per-episode env rebuild, action clip). Tested
     with a scripted FakeEnv + FakePolicy monkeypatched into eval_npz, so no
     MuJoCo rollout and no real weights are needed; answers are hand-computable.

The action-clip test is the eval-side half of the clip-parity contract that
test_deploy_parity.py pins on the deploy side: eval must grade the policy
through the SAME np.clip(action, -1, 1) the robot applies, or eval sees a
different controller than deploy runs.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # eval_npz.py, pidog_env.py at repo root
sys.path.insert(0, HERE)                    # deploy_pidog.py

import eval_npz  # noqa: E402


# ---- verdict(): the bar itself -------------------------------------------

def test_verdict_passes_at_exact_bar():
    """Thresholds are inclusive (>=) for fwd and steps; fwd>lat is strict."""
    assert eval_npz.verdict(200.0, 199.9, 800.0) is True


def test_verdict_fails_below_forward_bar():
    assert eval_npz.verdict(199.9, 0.0, 1000.0) is False


def test_verdict_fails_below_step_bar():
    """A policy that falls early fails even if it lunged far forward."""
    assert eval_npz.verdict(500.0, 0.0, 799.9) is False


def test_verdict_fails_when_lateral_dominates():
    """Straightness test: fwd must strictly exceed the (abs) lateral drift.
    Equal fwd and lat -> FAIL (crabbing sideways as far as it walks forward)."""
    assert eval_npz.verdict(300.0, 300.0, 1000.0) is False
    assert eval_npz.verdict(300.0, 299.0, 1000.0) is True


# ---- run_episodes(): episode accounting on a scripted fake env ------------

class FakePolicy:
    """Stands in for deploy_pidog.PolicyMLP; returns a deliberately out-of-range
    action so the clip test below has teeth."""

    def __init__(self, npz_path):
        self.npz_path = npz_path

    def __call__(self, obs):
        return np.full(8, 5.0)


class _Data:
    def __init__(self):
        self.qpos = np.zeros(2)


def _make_fake_env_cls(dx_m, dy_m, term_after, recorded_actions):
    """Env that moves (dx, dy) metres per step and terminates after term_after
    steps. Records every action it receives so the clip contract is checkable."""

    class FakeEnv:
        def __init__(self):
            self.data = _Data()
            self._t = 0

        def reset(self):
            self.data.qpos = np.zeros(2)
            self._t = 0
            return np.zeros(29, dtype=np.float32), {}

        def step(self, action):
            recorded_actions.append(np.asarray(action).copy())
            self._t += 1
            self.data.qpos[0] += dx_m
            self.data.qpos[1] += dy_m
            term = self._t >= term_after
            return np.zeros(29, dtype=np.float32), 0.0, term, False, {}

    return FakeEnv


def test_run_episodes_accounting_mm_abs_and_steps(monkeypatch):
    """100 steps of +1 mm fwd / -2 mm lateral per step, terminating at step 100:
    means must be fwd=+100 mm, lat=abs(-200)=200 mm, steps=100. Pins the
    m->mm conversion, the abs() on lateral (drift LEFT must count against
    straightness exactly like drift right), and early-termination step count."""
    actions = []
    monkeypatch.setattr(eval_npz, "PolicyMLP", FakePolicy)
    monkeypatch.setattr(eval_npz, "PiDogEnv",
                        _make_fake_env_cls(0.001, -0.002, 100, actions))
    mf, ml, ms = eval_npz.run_episodes("dummy.npz", n=3)
    assert abs(mf - 100.0) < 1e-9
    assert abs(ml - 200.0) < 1e-9
    assert abs(ms - 100.0) < 1e-9


def test_run_episodes_caps_at_1000_steps(monkeypatch):
    """An env that never terminates must be truncated by the evaluator's own
    1000-step cap — matching eval_mvp.py's episode protocol."""
    monkeypatch.setattr(eval_npz, "PolicyMLP", FakePolicy)
    monkeypatch.setattr(eval_npz, "PiDogEnv",
                        _make_fake_env_cls(0.0, 0.0, 10**9, []))
    _, _, ms = eval_npz.run_episodes("dummy.npz", n=1)
    assert ms == 1000.0


def test_run_episodes_clips_actions_like_deploy(monkeypatch):
    """Eval-side clip parity: the fake policy outputs 5.0 everywhere; every
    action the env sees must be inside [-1, 1] — the same clip deploy_pidog
    applies at inference. If eval ever stopped clipping, it would grade a
    controller the robot never runs."""
    actions = []
    monkeypatch.setattr(eval_npz, "PolicyMLP", FakePolicy)
    monkeypatch.setattr(eval_npz, "PiDogEnv",
                        _make_fake_env_cls(0.001, 0.0, 5, actions))
    eval_npz.run_episodes("dummy.npz", n=1)
    assert len(actions) == 5
    for a in actions:
        assert np.all(a <= 1.0) and np.all(a >= -1.0)
