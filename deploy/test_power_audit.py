"""Unit tests for power_audit.py delta accounting and the crawl reference shape.

The audit's claim is narrow: given a command stream, count per-tick moving
servos and sum |delta|. These tests pin that accounting on synthetic streams
with hand-computable answers, and pin the structural property the crawl
reference exists for (never more than one leg's joints commanded hard per tick).
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import power_audit  # noqa: E402
from power_audit import audit_stream, scripted_crawl_deg  # noqa: E402
from deploy_pidog import SMOOTHING_ALPHA  # noqa: E402


def test_audit_stream_static_gait_counts_zero():
    """A constant base gait with no policy commands nothing: 0 moving servos."""
    base = lambda phase: np.zeros(8)
    ms, ws, p95 = audit_stream(None, base, steps=50, move_deg=0.5, episodes=1, use_env=False)
    assert ms == 0
    assert ws == 0.0


def test_audit_stream_step_gait_known_worst_case():
    """A base gait that steps all 8 servos by 10 deg at phase>0: first tick delta
    is (1-alpha)*10 per servo -> sum 8*(1-alpha)*10, all 8 counted as moving."""
    def base(phase):
        return np.full(8, 10.0) if phase > 0 else np.zeros(8)
    ms, ws, _ = audit_stream(None, base, steps=30, move_deg=0.5, episodes=1, use_env=False)
    assert ms == 8
    expected_first = 8 * (1 - SMOOTHING_ALPHA) * 10.0
    assert abs(ws - expected_first) < 1e-6


def test_crawl_reference_moves_at_most_one_leg_hard():
    """The crawl reference's defining property: per phase sample, at most one
    leg's (hip, knee) pair deviates from stance by more than a small epsilon."""
    from deploy_pidog import ENV_STAND_DEG
    stance = np.array(ENV_STAND_DEG, float)
    for phase in np.linspace(0, 2 * np.pi, 97):
        dev = np.abs(scripted_crawl_deg(phase) - stance)
        legs_deviating = sum(
            1 for leg in range(4) if max(dev[2 * leg], dev[2 * leg + 1]) > 1.0
        )
        assert legs_deviating <= 1, f"phase {phase:.2f}: {legs_deviating} legs deviate"
